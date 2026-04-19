import time
import re
from groq import Groq

from backend.models.schemas import AgentResponse, SearchResult
from backend.utils.config import config
from backend.utils.telemetry import LLM_CALLS, LLM_LATENCY, RETRIEVAL_RESULTS, get_langfuse

SYSTEM_PROMPT = """You are an expert code assistant embedded in a developer's IDE.
You are given relevant code chunks retrieved from the developer's codebase.
Each chunk is labelled with its file path and line numbers.

Rules:
- Answer the developer's question using ONLY the provided code chunks.
- Always cite the exact file path and line numbers for every claim you make.
- Format citations inline like this: `path/to/file.py:42-67`
- If the answer spans multiple files, mention each file explicitly.
- Be concise and precise. Developers hate filler words.
- If the chunks don't contain enough information to answer, say so clearly.
- When showing code snippets in your answer, keep them short (< 15 lines).
- Never invent code that isn't in the provided chunks."""


def _build_context(results: list[SearchResult]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        c = r.chunk
        header = f"--- CHUNK {i} | {c.file_path} | lines {c.start_line}-{c.end_line}"
        if c.name:
            header += f" | {c.chunk_type}: {c.name}"
        if c.parent_name:
            header += f" (in class {c.parent_name})"
        parts.append(f"{header}\n{c.content}")
    return "\n\n".join(parts)


def _extract_citations(answer: str, results: list[SearchResult]) -> list[dict]:
    pattern = re.compile(r"`?([^\s`]+\.(py|js|ts|jsx|tsx)):(\d+)(?:-(\d+))?`?")
    found_paths = set()
    citations = []
    for match in pattern.finditer(answer):
        file_path  = match.group(1)
        start_line = int(match.group(3))
        end_line   = int(match.group(4)) if match.group(4) else start_line
        if file_path in found_paths:
            continue
        found_paths.add(file_path)
        meta = {"file_path": file_path, "start_line": start_line, "end_line": end_line}
        for r in results:
            if r.chunk.file_path.endswith(file_path) or file_path in r.chunk.file_path:
                meta["chunk_type"] = r.chunk.chunk_type
                meta["name"]       = r.chunk.name
                break
        citations.append(meta)
    return citations


def _try_langfuse_trace(lf, question: str, chunks: int, answer: str,
                        elapsed: float, usage, citations: list):
    """Best-effort Langfuse tracing — never raises, never blocks the query."""
    try:
        # Support both Langfuse v2 (trace) and v3 (start_trace)
        if hasattr(lf, "start_trace"):
            trace = lf.start_trace(name="query")
        elif hasattr(lf, "trace"):
            trace = lf.trace(name="query", input={"question": question})
        else:
            return

        span_input = {
            "question":  question,
            "model":     config.LLM_MODEL,
            "chunks":    chunks,
            "latency_s": round(elapsed, 3),
        }
        if usage:
            span_input["prompt_tokens"]     = usage.prompt_tokens
            span_input["completion_tokens"] = usage.completion_tokens

        if hasattr(trace, "span"):
            span = trace.span(name="groq-llm", input=span_input)
            span.end(output={"answer_length": len(answer), "citations": len(citations)})

        if hasattr(trace, "update"):
            trace.update(output={"answer": answer[:300], "citations": len(citations)})

        lf.flush()
    except Exception as e:
        print(f"[telemetry] Langfuse trace failed (non-fatal): {e}")


class SynthesisAgent:
    def __init__(self):
        self.client = Groq(api_key=config.GROQ_API_KEY)

    def answer(self, question: str, results: list[SearchResult]) -> AgentResponse:
        RETRIEVAL_RESULTS.observe(len(results))

        if not results:
            return AgentResponse(
                answer="No relevant code found in the indexed codebase.",
                citations=[], chunks_used=0, model_used=config.LLM_MODEL,
            )

        context = _build_context(results)
        user_message = f"""Here are the relevant code chunks from the codebase:

{context}

---
Developer question: {question}

Answer with specific file paths and line numbers."""

        LLM_CALLS.inc()
        t0 = time.perf_counter()

        try:
            response = self.client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            answer_text = response.choices[0].message.content or ""
            usage       = response.usage
        except Exception as e:
            return AgentResponse(
                answer=f"LLM error: {str(e)}",
                citations=[], chunks_used=len(results), model_used=config.LLM_MODEL,
            )

        elapsed  = time.perf_counter() - t0
        LLM_LATENCY.observe(elapsed)
        citations = _extract_citations(answer_text, results)

        # Best-effort tracing — if Langfuse isn't configured or API changed, skip silently
        lf = get_langfuse()
        if lf:
            _try_langfuse_trace(lf, question, len(results), answer_text, elapsed, usage, citations)

        return AgentResponse(
            answer=answer_text,
            citations=citations,
            chunks_used=len(results),
            model_used=config.LLM_MODEL,
        )

import re
from groq import Groq

from backend.models.schemas import AgentResponse, SearchResult
from backend.utils.config import config

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
    """Format retrieved chunks into a readable context block for the LLM."""
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
    """
    Pull out every citation the LLM wrote (file:line format)
    and enrich with metadata from our search results.
    """
    # Match patterns like `src/auth.py:12-45` or `utils/db.py:88`
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

        # Try to find the matching chunk for extra metadata
        meta = {"file_path": file_path, "start_line": start_line, "end_line": end_line}
        for r in results:
            if r.chunk.file_path.endswith(file_path) or file_path in r.chunk.file_path:
                meta["chunk_type"] = r.chunk.chunk_type
                meta["name"]       = r.chunk.name
                break

        citations.append(meta)

    return citations


class SynthesisAgent:
    def __init__(self):
        self.client = Groq(api_key=config.GROQ_API_KEY)

    def answer(
        self,
        question: str,
        results: list[SearchResult],
    ) -> AgentResponse:
        if not results:
            return AgentResponse(
                answer="No relevant code found in the indexed codebase for this question.",
                citations=[],
                chunks_used=0,
                model_used=config.LLM_MODEL,
            )

        context = _build_context(results)

        user_message = f"""Here are the relevant code chunks from the codebase:

{context}

---
Developer question: {question}

Answer with specific file paths and line numbers."""

        try:
            response = self.client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.1,      # low temp = precise, factual answers
                max_tokens=1024,
            )
            answer_text = response.choices[0].message.content or ""
        except Exception as e:
            return AgentResponse(
                answer=f"LLM error: {str(e)}",
                citations=[],
                chunks_used=len(results),
                model_used=config.LLM_MODEL,
            )

        citations = _extract_citations(answer_text, results)

        return AgentResponse(
            answer=answer_text,
            citations=citations,
            chunks_used=len(results),
            model_used=config.LLM_MODEL,
        )
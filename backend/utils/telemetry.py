"""
Central telemetry module.
Prometheus custom metrics + Langfuse LLM tracing.
"""
import os
from prometheus_client import Counter, Histogram, Gauge
from langfuse import Langfuse

# ── Prometheus custom metrics ─────────────────────────────────────
CHUNKS_INDEXED = Gauge(
    "codebase_agent_chunks_indexed_total",
    "Total number of code chunks currently indexed",
)
LLM_CALLS = Counter(
    "codebase_agent_llm_calls_total",
    "Total LLM calls made to Groq",
)
LLM_LATENCY = Histogram(
    "codebase_agent_llm_latency_seconds",
    "LLM call latency in seconds",
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0],
)
RETRIEVAL_RESULTS = Histogram(
    "codebase_agent_retrieval_results",
    "Number of chunks retrieved per query",
    buckets=[1, 2, 4, 6, 8, 10, 12],
)
INDEX_OPERATIONS = Counter(
    "codebase_agent_index_operations_total",
    "Total index operations (full + incremental)",
    ["operation_type"],   # "full" or "incremental"
)

# ── Langfuse client (lazy — only if keys are set) ─────────────────
_langfuse: Langfuse | None = None

def get_langfuse() -> Langfuse | None:
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    if pk and sk:
        _langfuse = Langfuse(
            public_key=pk,
            secret_key=sk,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        print("[telemetry] Langfuse tracing enabled")
    else:
        print("[telemetry] Langfuse keys not set — tracing disabled")
    return _langfuse

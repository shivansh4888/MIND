import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator

from backend.agents.ingestion_agent import IngestionAgent
from backend.agents.retrieval_agent import RetrievalAgent
from backend.agents.synthesis_agent import SynthesisAgent
from backend.models.schemas import AgentResponse, IndexStatus, QueryRequest
from backend.utils.file_watcher import FileWatcher
from backend.utils.telemetry import CHUNKS_INDEXED, INDEX_OPERATIONS, get_langfuse

ingestion_agent: IngestionAgent | None = None
retrieval_agent: RetrievalAgent | None = None
synthesis_agent: SynthesisAgent | None = None
file_watcher:    FileWatcher    | None = None
index_status:    IndexStatus    = IndexStatus()
current_root:    str            = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingestion_agent, retrieval_agent, synthesis_agent
    ingestion_agent = IngestionAgent()
    retrieval_agent = RetrievalAgent()
    synthesis_agent = SynthesisAgent()
    get_langfuse()   # initialise tracing at startup
    print("[server] All agents initialised")
    yield
    if file_watcher:
        file_watcher.stop()
    print("[server] Shutdown complete")


app = FastAPI(title="Codebase Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus: auto-instrument all HTTP endpoints ────────────────
Instrumentator().instrument(app).expose(app, endpoint="/metrics")


class IndexRequest(BaseModel):
    root_path: str


@app.get("/health")
async def health():
    return {"status": "ok", "indexed_chunks": index_status.total_chunks}


@app.get("/status")
async def status() -> IndexStatus:
    return index_status


@app.post("/index")
async def index(req: IndexRequest):
    global index_status, current_root, file_watcher

    root = Path(req.root_path).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {root}")
    if index_status.is_indexing:
        raise HTTPException(status_code=409, detail="Indexing already in progress")

    current_root = str(root)

    def _run():
        global index_status, file_watcher
        INDEX_OPERATIONS.labels(operation_type="full").inc()
        index_status = ingestion_agent.index_project(
            current_root,
            progress_cb=lambda f, c, t: print(f"[index] {c}/{t} {f}"),
        )
        CHUNKS_INDEXED.set(index_status.total_chunks)
        print(f"[server] Index complete — {index_status.total_chunks} chunks")

        if file_watcher:
            file_watcher.stop()
        file_watcher = FileWatcher(
            current_root,
            on_change_cb=_on_file_change,
        )
        file_watcher.start()

    threading.Thread(target=_run, daemon=True).start()
    return {"message": f"Indexing started for {root}", "root": str(root)}


def _on_file_change(file_path: str):
    INDEX_OPERATIONS.labels(operation_type="incremental").inc()
    ingestion_agent.index_single_file(file_path)
    # Update gauge after incremental re-index
    try:
        import sqlite3
        conn = sqlite3.connect(ingestion_agent.db_path if hasattr(ingestion_agent, "db_path") else "data/symbols.db")
        count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        conn.close()
        CHUNKS_INDEXED.set(count)
    except Exception:
        pass


@app.post("/query", response_model=AgentResponse)
async def query(req: QueryRequest):
    if index_status.total_chunks == 0 and not index_status.is_indexing:
        raise HTTPException(status_code=400, detail="No index found. Call /index first.")
    results  = retrieval_agent.search(req.question, top_k=req.top_k)
    response = synthesis_agent.answer(req.question, results)
    return response


@app.delete("/index")
async def clear_index():
    global index_status
    try:
        ingestion_agent.collection.delete(
            where={"chunk_type": {"$ne": "__never__"}}
        )
    except Exception:
        pass
    import sqlite3
    conn = sqlite3.connect("data/symbols.db")
    conn.execute("DELETE FROM symbols")
    conn.commit()
    conn.close()
    index_status = IndexStatus()
    CHUNKS_INDEXED.set(0)
    return {"message": "Index cleared"}

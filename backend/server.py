import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.agents.ingestion_agent import IngestionAgent
from backend.agents.retrieval_agent import RetrievalAgent
from backend.agents.synthesis_agent import SynthesisAgent
from backend.models.schemas import AgentResponse, IndexStatus, QueryRequest
from backend.utils.file_watcher import FileWatcher


# ------------------------------------------------------------------ #
#  Shared state                                                        #
# ------------------------------------------------------------------ #

ingestion_agent: IngestionAgent | None = None
retrieval_agent: RetrievalAgent | None = None
synthesis_agent: SynthesisAgent | None = None
file_watcher:    FileWatcher    | None = None
index_status:    IndexStatus    = IndexStatus()
current_root:    str            = ""


# ------------------------------------------------------------------ #
#  Lifespan — runs once on startup                                    #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ingestion_agent, retrieval_agent, synthesis_agent
    ingestion_agent = IngestionAgent()
    retrieval_agent = RetrievalAgent()
    synthesis_agent = SynthesisAgent()
    print("[server] All agents initialised")
    yield
    if file_watcher:
        file_watcher.stop()
    print("[server] Shutdown complete")


app = FastAPI(
    title="Codebase Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # VS Code webview needs this
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ #
#  Request models                                                      #
# ------------------------------------------------------------------ #

class IndexRequest(BaseModel):
    root_path: str


# ------------------------------------------------------------------ #
#  Endpoints                                                           #
# ------------------------------------------------------------------ #

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
        print(f"[server] Indexing {current_root}")
        index_status = ingestion_agent.index_project(
            current_root,
            progress_cb=lambda f, c, t: print(f"[index] {c}/{t} {f}"),
        )
        print(f"[server] Index complete — {index_status.total_chunks} chunks")

        # Start file watcher after initial index
        if file_watcher:
            file_watcher.stop()
        file_watcher = FileWatcher(
            current_root,
            on_change_cb=ingestion_agent.index_single_file,
        )
        file_watcher.start()

    threading.Thread(target=_run, daemon=True).start()
    return {"message": f"Indexing started for {root}", "root": str(root)}


@app.post("/query", response_model=AgentResponse)
async def query(req: QueryRequest):
    if index_status.total_chunks == 0 and not index_status.is_indexing:
        raise HTTPException(
            status_code=400,
            detail="No index found. Call /index first.",
        )

    results = retrieval_agent.search(req.question, top_k=req.top_k)
    response = synthesis_agent.answer(req.question, results)
    return response


@app.delete("/index")
async def clear_index():
    """Wipe the index — useful when switching projects."""
    global index_status
    try:
        ingestion_agent.collection.delete(
            where={"chunk_type": {"$ne": "__never__"}}  # delete all
        )
    except Exception:
        pass
    import sqlite3
    conn = sqlite3.connect(ingestion_agent.db_path if hasattr(ingestion_agent, 'db_path') else "data/symbols.db")
    conn.execute("DELETE FROM symbols")
    conn.commit()
    conn.close()
    index_status = IndexStatus()
    return {"message": "Index cleared"}
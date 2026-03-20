import sqlite3
import time
import threading
from pathlib import Path
from typing import Callable, Optional

import chromadb
import cohere

from backend.tools.ast_chunker import chunk_file
from backend.models.schemas import CodeChunk, IndexStatus
from backend.utils.config import config

# Thread-local storage so each thread gets its own SQLite connection
_local = threading.local()


def _get_db() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        Path(config.SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.SQLITE_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                chunk_id    TEXT PRIMARY KEY,
                file_path   TEXT,
                name        TEXT,
                chunk_type  TEXT,
                start_line  INTEGER,
                end_line    INTEGER,
                content     TEXT,
                language    TEXT,
                parent_name TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON symbols(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file ON symbols(file_path)")
        conn.commit()
        _local.conn = conn
    return _local.conn


def _get_chroma_collection(client: chromadb.Client):
    return client.get_or_create_collection(
        name="codebase",
        metadata={"hnsw:space": "cosine"},
    )


def _embed_batch(co: cohere.Client, texts: list[str]) -> list[list[float]]:
    response = co.embed(
        texts=texts,
        model=config.EMBED_MODEL,
        input_type="search_document",
    )
    return response.embeddings


def _collect_files(root: str) -> list[str]:
    files = []
    root_path = Path(root)
    for path in root_path.rglob("*"):
        if path.is_file():
            if any(part in config.IGNORE_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in config.SUPPORTED_EXTENSIONS:
                files.append(str(path))
    return sorted(files)


class IngestionAgent:
    def __init__(self):
        Path(config.CHROMA_PATH).mkdir(parents=True, exist_ok=True)
        self.chroma     = chromadb.PersistentClient(path=config.CHROMA_PATH)
        self.collection = _get_chroma_collection(self.chroma)
        self.co         = cohere.Client(api_key=config.COHERE_API_KEY)
        self.status     = IndexStatus()
        # Ensure table exists in main thread too
        _get_db()

    def index_project(
        self,
        root_path: str,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ) -> IndexStatus:
        self.status = IndexStatus(is_indexing=True)
        files = _collect_files(root_path)
        self.status.total_files = len(files)

        all_chunks: list[CodeChunk] = []

        # --- Chunking pass ---
        for i, fpath in enumerate(files):
            if progress_cb:
                progress_cb(fpath, i + 1, len(files))
            try:
                chunks = chunk_file(fpath)
                all_chunks.extend(chunks)
                self.status.indexed_files.append(fpath)
            except Exception as e:
                print(f"[ingestion] Chunk error {fpath}: {e}")
                self.status.failed_files.append(fpath)

        self.status.total_chunks = len(all_chunks)
        print(f"[ingestion] {len(all_chunks)} chunks from {len(files)} files")

        # --- Embedding + storage pass (batches of 64) ---
        BATCH = 64
        db = _get_db()   # get this thread's connection

        for i in range(0, len(all_chunks), BATCH):
            batch = all_chunks[i : i + BATCH]
            texts = [self._chunk_to_text(c) for c in batch]

            try:
                embeddings = _embed_batch(self.co, texts)
            except Exception as e:
                print(f"[ingestion] Embed error batch {i}: {e}")
                time.sleep(2)
                try:
                    embeddings = _embed_batch(self.co, texts)
                except Exception as e2:
                    print(f"[ingestion] Embed retry failed: {e2}")
                    continue

            # Write to ChromaDB
            self.collection.upsert(
                ids=[c.chunk_id for c in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[self._chunk_to_meta(c) for c in batch],
            )

            # Write to SQLite (using this thread's connection)
            db.executemany(
                """INSERT OR REPLACE INTO symbols
                   (chunk_id, file_path, name, chunk_type,
                    start_line, end_line, content, language, parent_name)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        c.chunk_id, c.file_path, c.name or "",
                        c.chunk_type, c.start_line, c.end_line,
                        c.content[:1000], c.language.value,
                        c.parent_name or "",
                    )
                    for c in batch
                ],
            )
            db.commit()
            print(f"[ingestion] Stored batch {i // BATCH + 1}/{(len(all_chunks) + BATCH - 1) // BATCH}")

        self.status.is_indexing = False
        return self.status

    def index_single_file(self, file_path: str):
        """Re-index one file on save (called from watcher thread)."""
        db = _get_db()

        old = db.execute(
            "SELECT chunk_id FROM symbols WHERE file_path=?", (file_path,)
        ).fetchall()
        if old:
            old_ids = [r[0] for r in old]
            self.collection.delete(ids=old_ids)
            db.execute("DELETE FROM symbols WHERE file_path=?", (file_path,))
            db.commit()

        chunks = chunk_file(file_path)
        if not chunks:
            return

        texts = [self._chunk_to_text(c) for c in chunks]
        try:
            embeddings = _embed_batch(self.co, texts)
        except Exception as e:
            print(f"[ingestion] Re-index embed error {file_path}: {e}")
            return

        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=texts,
            metadatas=[self._chunk_to_meta(c) for c in chunks],
        )
        db.executemany(
            """INSERT OR REPLACE INTO symbols
               (chunk_id, file_path, name, chunk_type,
                start_line, end_line, content, language, parent_name)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    c.chunk_id, c.file_path, c.name or "",
                    c.chunk_type, c.start_line, c.end_line,
                    c.content[:1000], c.language.value,
                    c.parent_name or "",
                )
                for c in chunks
            ],
        )
        db.commit()
        print(f"[ingestion] Re-indexed {file_path} → {len(chunks)} chunks")

    @staticmethod
    def _chunk_to_text(c: CodeChunk) -> str:
        parts = [f"File: {c.file_path}"]
        if c.name:
            parts.append(f"{c.chunk_type.capitalize()}: {c.name}")
        if c.parent_name:
            parts.append(f"Inside class: {c.parent_name}")
        if c.docstring:
            parts.append(f"Description: {c.docstring}")
        parts.append(c.content)
        return "\n".join(parts)

    @staticmethod
    def _chunk_to_meta(c: CodeChunk) -> dict:
        return {
            "file_path":   c.file_path,
            "chunk_type":  c.chunk_type,
            "name":        c.name or "",
            "start_line":  c.start_line,
            "end_line":    c.end_line,
            "language":    c.language.value,
            "parent_name": c.parent_name or "",
        }
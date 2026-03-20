import sqlite3
from pathlib import Path

import chromadb
import cohere
from rank_bm25 import BM25Okapi

from backend.models.schemas import CodeChunk, Language, SearchResult
from backend.utils.config import config


def _meta_to_chunk(doc: str, meta: dict, score: float) -> CodeChunk:
    return CodeChunk(
        chunk_id=meta.get("chunk_id", ""),
        file_path=meta.get("file_path", ""),
        language=Language(meta.get("language", "unknown")),
        chunk_type=meta.get("chunk_type", ""),
        name=meta.get("name") or None,
        content=doc,
        start_line=int(meta.get("start_line", 0)),
        end_line=int(meta.get("end_line", 0)),
        parent_name=meta.get("parent_name") or None,
    )


class RetrievalAgent:
    def __init__(self):
        self.chroma = chromadb.PersistentClient(path=config.CHROMA_PATH)
        self.collection = self.chroma.get_or_create_collection(
            name="codebase",
            metadata={"hnsw:space": "cosine"},
        )
        self.co = cohere.Client(api_key=config.COHERE_API_KEY)
        self.db_path = config.SQLITE_PATH

    # ------------------------------------------------------------------ #
    #  Public entry point                                                  #
    # ------------------------------------------------------------------ #

    def search(self, question: str, top_k: int = None) -> list[SearchResult]:
        """
        Hybrid search: semantic via ChromaDB + keyword via BM25 over SQLite.
        Results are merged and deduplicated, ranked by combined score.
        """
        k = top_k or config.MAX_RESULTS

        semantic_results = self._semantic_search(question, k=k)
        keyword_results  = self._keyword_search(question, k=k)

        merged = self._merge(semantic_results, keyword_results, top_k=k)
        return merged

    # ------------------------------------------------------------------ #
    #  Semantic search                                                     #
    # ------------------------------------------------------------------ #

    def _semantic_search(self, question: str, k: int) -> list[SearchResult]:
        try:
            response = self.co.embed(
                texts=[question],
                model=config.EMBED_MODEL,
                input_type="search_query",   # different input_type for queries
            )
            query_embedding = response.embeddings[0]
        except Exception as e:
            print(f"[retrieval] Embed error: {e}")
            return []

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(k, self.collection.count() or 1),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"[retrieval] ChromaDB query error: {e}")
            return []

        out: list[SearchResult] = []
        docs      = results["documents"][0]
        metas     = results["metadatas"][0]
        distances = results["distances"][0]

        for doc, meta, dist in zip(docs, metas, distances):
            score = 1.0 - dist          # cosine distance → similarity
            chunk = _meta_to_chunk(doc, meta, score)
            out.append(SearchResult(chunk=chunk, score=score, match_type="semantic"))

        return out

    # ------------------------------------------------------------------ #
    #  Keyword search (BM25 over SQLite corpus)                           #
    # ------------------------------------------------------------------ #

    def _keyword_search(self, question: str, k: int) -> list[SearchResult]:
        if not Path(self.db_path).exists():
            return []

        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT chunk_id, file_path, name, chunk_type, "
                "start_line, end_line, content, language, parent_name "
                "FROM symbols"
            ).fetchall()
            conn.close()
        except Exception as e:
            print(f"[retrieval] SQLite error: {e}")
            return []

        if not rows:
            return []

        # Tokenise each document for BM25
        corpus_tokens = [
            self._tokenise(
                f"{r[2]} {r[3]} {r[4]} {r[6]}"   # name + type + line + content
            )
            for r in rows
        ]
        query_tokens = self._tokenise(question)

        bm25   = BM25Okapi(corpus_tokens)
        scores = bm25.get_scores(query_tokens)

        # Take top-k by score
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

        out: list[SearchResult] = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            r = rows[idx]
            chunk = CodeChunk(
                chunk_id=r[0],
                file_path=r[1],
                language=Language(r[7]),
                chunk_type=r[3],
                name=r[2] or None,
                content=r[6],
                start_line=r[4],
                end_line=r[5],
                parent_name=r[8] or None,
            )
            # Normalise BM25 score to 0-1 range roughly
            norm_score = min(scores[idx] / 10.0, 1.0)
            out.append(SearchResult(chunk=chunk, score=norm_score, match_type="keyword"))

        return out

    # ------------------------------------------------------------------ #
    #  Merge + deduplicate                                                 #
    # ------------------------------------------------------------------ #

    def _merge(
        self,
        semantic: list[SearchResult],
        keyword: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """
        Reciprocal Rank Fusion — gives credit to results that rank well
        in BOTH semantic and keyword, surfaces them to the top.
        """
        RRF_K = 60
        scores: dict[str, float] = {}
        best:   dict[str, SearchResult] = {}

        for rank, result in enumerate(semantic):
            cid = result.chunk.chunk_id or result.chunk.file_path
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank + 1)
            best[cid]   = result

        for rank, result in enumerate(keyword):
            cid = result.chunk.chunk_id or result.chunk.file_path
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank + 1)
            if cid not in best:
                best[cid] = result

        ranked = sorted(scores.keys(), key=lambda c: scores[c], reverse=True)[:top_k]

        merged = []
        for cid in ranked:
            r = best[cid]
            r.score = scores[cid]
            merged.append(r)

        return merged

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tokenise(text: str) -> list[str]:
        import re
        # Split on non-alphanumeric, lowercase, drop empty
        tokens = re.split(r"[^a-zA-Z0-9_]+", text.lower())
        return [t for t in tokens if t]

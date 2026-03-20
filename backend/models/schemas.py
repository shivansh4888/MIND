from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class Language(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"


class CodeChunk(BaseModel):
    chunk_id: str
    file_path: str
    language: Language
    chunk_type: str                    # "function", "class", "module", "import_block"
    name: Optional[str] = None         # function/class name if applicable
    content: str                       # raw source text of this chunk
    start_line: int
    end_line: int
    parent_name: Optional[str] = None  # class name if this is a method
    docstring: Optional[str] = None
    imports: list[str] = Field(default_factory=list)
    embedding: Optional[list[float]] = None


class IndexStatus(BaseModel):
    total_files: int = 0
    total_chunks: int = 0
    indexed_files: list[str] = Field(default_factory=list)
    failed_files: list[str] = Field(default_factory=list)
    is_indexing: bool = False


class QueryRequest(BaseModel):
    question: str
    top_k: int = 8
    include_context: bool = True


class SearchResult(BaseModel):
    chunk: CodeChunk
    score: float
    match_type: str   # "semantic" or "keyword"


class AgentResponse(BaseModel):
    answer: str
    citations: list[dict] = Field(default_factory=list)
    chunks_used: int = 0
    model_used: str = ""

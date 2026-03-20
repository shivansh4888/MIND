from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

class Config:
    GROQ_API_KEY: str     = os.getenv("GROQ_API_KEY", "")
    COHERE_API_KEY: str   = os.getenv("COHERE_API_KEY", "")
    CHROMA_PATH: str      = os.getenv("CHROMA_PATH", "./data/chroma")
    SQLITE_PATH: str      = os.getenv("SQLITE_PATH", "./data/symbols.db")
    LLM_MODEL: str        = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    EMBED_MODEL: str      = os.getenv("EMBED_MODEL", "embed-english-v3.0")
    MAX_RESULTS: int      = int(os.getenv("MAX_RESULTS", "8"))
    CHUNK_MAX_LINES: int  = int(os.getenv("CHUNK_MAX_LINES", "60"))

    SUPPORTED_EXTENSIONS = {
        ".py":   "python",
        ".js":   "javascript",
        ".ts":   "typescript",
        ".jsx":  "javascript",
        ".tsx":  "typescript",
    }

    IGNORE_DIRS = {
        "node_modules", ".git", ".venv", "venv", "__pycache__",
        "dist", "build", ".next", "coverage", ".pytest_cache",
        "data", ".mypy_cache", "eggs", ".eggs",
    }

config = Config()

# Codebase Agent

A production-grade AI developer tool that indexes your entire codebase and answers natural language questions about it — with exact file and line citations.

Built as a VS Code extension backed by a local Python sidecar using a multi-agent RAG pipeline. Fully free, fully local, fully private.



## What it does

- Ask "where is authentication handled?" and get a cited answer pointing to the exact file and line
- Understands code structure via AST parsing — not naive line-by-line chunking
- Hybrid search: semantic similarity (Cohere embeddings) + keyword (BM25) merged via Reciprocal Rank Fusion
- Auto re-indexes files on save via a file watcher
- Works on Python, JavaScript, and TypeScript codebases
- Clickable citations in the VS Code sidebar jump directly to the referenced line

## Architecture
```
VS Code Extension (TypeScript)
        │  JSON over localhost:57384
        ▼
  Orchestrator / FastAPI server
        │
   ┌────┴────┐──────────────┐
   ▼         ▼              ▼
Ingestion  Retrieval    Synthesis
 Agent      Agent        Agent
   │         │              │
Tree-sitter  ChromaDB     Groq API
AST parser   + BM25      (Llama-3.3-70b)
   │
Cohere Embed
(embed-english-v3.0)
```

## Free stack

| Component | Tool | Cost |
|-----------|------|------|
| LLM inference | Groq — Llama-3.3-70b | Free tier |
| Embeddings | Cohere embed-english-v3.0 | 1M tokens/month free |
| Vector store | ChromaDB | Local, unlimited |
| AST parsing | Tree-sitter | Open source |
| Symbol index | SQLite | Local |
| Extension | VS Code Extension API | Free |

## Getting started

### Prerequisites

- Python 3.10+
- Node.js 18+
- VS Code 1.85+
- Free API keys: [Groq](https://console.groq.com) · [Cohere](https://dashboard.cohere.com)

### 1. Clone and set up
```bash
git clone https://github.com/yourusername/codebase-agent
cd codebase-agent
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn chromadb cohere groq tree-sitter \
    tree-sitter-python tree-sitter-javascript watchdog rank-bm25 \
    pydantic python-dotenv aiofiles
```

### 2. Configure API keys
```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add your Groq and Cohere API keys
```

### 3. Start the sidecar server
```bash
python3 run_server.py
```

### 4. Install the VS Code extension
```bash
cd vscode-extension
npm install && npx tsc -p ./
npx @vscode/vsce package --no-dependencies
code --install-extension codebase-agent-0.1.0.vsix
```

### 5. Use it

- Open any Python or JS/TS project in VS Code
- Click the Codebase Agent icon in the Activity Bar
- Click **Index workspace**
- Ask anything about your code

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health + chunk count |
| GET | `/status` | Full index status |
| POST | `/index` | Index a folder `{"root_path": "/path"}` |
| POST | `/query` | Ask a question `{"question": "...", "top_k": 8}` |
| DELETE | `/index` | Clear the index |

## How it works

**Ingestion agent** — walks the project directory, runs every `.py`, `.js`, `.ts` file through Tree-sitter to build an AST, then chunks at meaningful boundaries (functions, classes, import blocks). Each chunk is enriched with metadata (file path, line numbers, docstring, parent class) before embedding.

**Retrieval agent** — embeds the user's question with Cohere (`input_type: search_query`) and queries ChromaDB for the top-k semantically similar chunks. Simultaneously runs BM25 keyword search over the SQLite symbol index. Results are merged using Reciprocal Rank Fusion.

**Synthesis agent** — packages retrieved chunks into a structured prompt with file/line headers, calls Groq (Llama-3.3-70b at 0.1 temperature), extracts citations from the response using regex, and returns a structured `AgentResponse` with answer + citation list.

**File watcher** — uses `watchdog` to monitor the indexed directory. On every file save, debounces 2 seconds, deletes old chunks for that file from ChromaDB and SQLite, re-chunks and re-embeds the updated file.

## Project structure
```
codebase-agent/
├── backend/
│   ├── agents/
│   │   ├── ingestion_agent.py   # AST chunking + embedding pipeline
│   │   ├── retrieval_agent.py   # Hybrid semantic + BM25 search
│   │   └── synthesis_agent.py   # Groq LLM + citation extraction
│   ├── tools/
│   │   └── ast_chunker.py       # Tree-sitter AST parser for Py/JS/TS
│   ├── models/
│   │   └── schemas.py           # Pydantic data models
│   ├── utils/
│   │   ├── config.py            # Env config
│   │   └── file_watcher.py      # Watchdog-based auto re-indexer
│   └── server.py                # FastAPI server + agent orchestration
├── vscode-extension/
│   ├── src/
│   │   └── extension.ts         # Full VS Code extension
│   ├── media/
│   │   └── icon.svg
│   └── package.json
├── run_server.py                 # Server entrypoint
└── README.md
```


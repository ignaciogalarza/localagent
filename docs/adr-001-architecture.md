# ADR-001: LocalAgent Architecture

## Status
Accepted (Updated Feb 2026 - Smart Search)

## Context
We need a system where Claude delegates mechanical tasks (file scanning, semantic search, summarization) to local subagents. The system must prioritize token efficiency and single-developer laptop deployment.

## Decision

### Architecture: Lean HTTP Broker + Semantic Search

**Selected Option**: Minimal Python broker exposes three subagents via HTTP. ChromaDB for vector search. SQLite for cache. Ollama for LLM summarization.

**Rationale**:
- Maximum token efficiency (~99% reduction vs reading files)
- Semantic search enables natural language code exploration
- SQLite + ChromaDB provide local persistence
- Ollama manages model lifecycle cleanly

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude (Orchestrator)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   LocalAgent MCP Server                      │
│  Tools: scan_files, summarize_file, smart_search            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      HTTP Broker (:8000)                     │
│  Dispatches to: file_scanner, summarizer, smart_searcher    │
└─────────────────────────────────────────────────────────────┘
           │                    │                    │
           ▼                    ▼                    ▼
    ┌──────────┐         ┌──────────┐         ┌──────────────┐
    │ Scanner  │         │Summarizer│         │Smart Searcher│
    │(pathlib) │         │ (Ollama) │         │  (ChromaDB)  │
    └──────────┘         └──────────┘         └──────────────┘
                              │                       │
                              ▼                       ▼
                         ┌────────┐            ┌──────────┐
                         │ Ollama │            │ ChromaDB │
                         └────────┘            └──────────┘
```

### Subagents

1. **file_scanner**: Glob patterns, SHA256 hashing, file listing
2. **summarizer**: Ollama integration for content compression
3. **smart_searcher**: ChromaDB vector search + Ollama summarization

### Storage

```
~/.localagent/
├── chroma/                 # Vector embeddings (ChromaDB)
│   └── index-manifest.json # File hash tracking for incremental updates
└── cache/
    └── cache.db            # Summary cache (SQLite, LRU eviction)
```

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vector DB | ChromaDB | Simple, embedded, good embeddings |
| Local LLM | Mistral-7B via Ollama | Good quality/speed for summarization |
| Transport | HTTP localhost:8000 | Easy debugging with curl |
| Indexing | Incremental via SHA256 manifest | Only re-index changed files |
| Chunking | 200 lines, 50-line overlap | Balance between context and granularity |

## Consequences

### Positive
- ~99% token savings vs reading raw files
- Natural language code search
- Simple codebase (~1200 lines)
- Easy local development
- No external service dependencies (all local)

### Negative
- Requires Ollama for summarization (graceful fallback exists)
- Initial indexing takes a few seconds per project
- ChromaDB adds ~100MB to dependencies

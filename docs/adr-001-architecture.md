# ADR-001: LocalAgent Architecture

## Status
Accepted

## Context
We need a system where Claude acts as a high-level planner delegating mechanical tasks to local subagents. The system must prioritize token efficiency, safety, and single-developer laptop deployment.

## Decision

### Architecture: Subprocess Pool with Shared Memory

**Selected Option**: Central Python broker spawns subagent workers as subprocesses. SQLite for task/cache persistence. Ollama runs as separate daemon for 7B model.

**Rationale**:
- Process isolation without container overhead
- Zero external dependencies (no Redis)
- SQLite provides durability + easy debugging
- Ollama manages model lifecycle cleanly

### Key Components

1. **HTTP Broker** (FastAPI on localhost:8000)
   - Receives delegation requests via `/delegate` endpoint
   - Routes to appropriate subagent
   - Manages session state and caching

2. **Subagents**
   - `file_scanner`: Glob patterns, content extraction, SHA256 hashing
   - `summarizer`: Ollama integration for content compression
   - `bash_runner`: Sandboxed command execution via bubblewrap

3. **Artifact Cache** (SQLite)
   - Content-addressable storage
   - LRU eviction (max 1000 entries)
   - Shared across all subagents

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Local LLM | Mistral-7B-Q4 via Ollama | Good quality/speed balance |
| Sandbox | bubblewrap (bwrap) | Lightweight, no root needed |
| Transport | HTTP localhost:8000 | Easy debugging with curl |
| Delegation | Hybrid (Eager + Lazy) | Summary always returned, fetch_detail on demand |
| Confidence | LLM self-assessment | 7B model rates its own confidence (0-1) |
| Session Context | Narrow stateful tracking | ≤200 token summary, no raw artifacts |

## Consequences

### Positive
- ~80% token savings via aggressive caching + pointer refs
- Safe bash execution via bubblewrap sandbox
- Easy local development and debugging
- No external service dependencies

### Negative
- Unix-only for some optimizations (bubblewrap)
- Shared memory requires careful lifecycle management
- Single-machine deployment only

### Risks and Mitigations
- **Risk**: Shared memory leaks if subagent crashes
- **Mitigation**: Broker tracks all shared memory blocks; cleanup on task timeout

## References
- [Bubblewrap](https://github.com/containers/bubblewrap)
- [Ollama](https://ollama.ai/)
- [FastAPI](https://fastapi.tiangolo.com/)

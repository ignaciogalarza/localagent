# Lean Refactor: Strip to Essential Components

## Objective

Remove unnecessary complexity. Keep only what saves tokens.

## Remove

| Component | Reason |
|-----------|--------|
| bash_runner | No efficiency gain, Claude's Bash tool works fine |
| Sandbox (bwrap) | Only needed for bash_runner |
| Policies system | Only needed for bash_runner restrictions |
| prompt_engine.py | Over-engineered, summarizer works without it |
| Session management | Unnecessary for stateless scan/summarize |
| Retry queue | Premature optimization |

## Keep

| Component | Purpose |
|-----------|---------|
| file_scanner | Scan files, return paths + hashes + summary |
| summarizer | Compress large content via Ollama |
| cache | Avoid re-summarizing unchanged files (by hash) |
| /delegate endpoint | Single entry point |
| /health endpoint | Verify Ollama is running |

## New Architecture

```
┌─────────────────────────────────────────┐
│  MCP Server (mcp-localagent)            │
│  - Tool: scan_files(patterns, path)     │
│  - Tool: summarize(content, max_tokens) │
│  - Tool: get_file(path)                 │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│  LocalAgent Broker (localhost:8000)     │
│                                         │
│  POST /delegate                         │
│    tool_name: file_scanner | summarizer │
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ file_scanner │  │  summarizer  │    │
│  │  (pathlib)   │  │   (Ollama)   │    │
│  └──────────────┘  └──────────────┘    │
│           │               │             │
│           └───────┬───────┘             │
│                   ▼                     │
│           ┌──────────────┐              │
│           │    cache     │              │
│           │   (SQLite)   │              │
│           └──────────────┘              │
└─────────────────────────────────────────┘
```

## MCP Server Requirements

```python
# mcp_localagent/server.py - ENTIRE FILE
from mcp import Server
import httpx

server = Server("localagent")
BROKER = "http://localhost:8000"

@server.tool()
async def scan_files(patterns: list[str], root: str, max_tokens: int = 200) -> dict:
    """Scan files matching patterns, return summary + paths."""
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BROKER}/delegate", json={
            "task_id": f"scan-{id(patterns)}",
            "tool_name": "file_scanner",
            "input_refs": [{"type": "glob", "value": p} for p in patterns],
            "max_summary_tokens": max_tokens
        })
        return r.json()

@server.tool()
async def summarize_file(path: str, max_tokens: int = 200) -> dict:
    """Summarize a file's content."""
    content = open(path).read()
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BROKER}/delegate", json={
            "task_id": f"sum-{hash(path)}",
            "tool_name": "summarizer",
            "input_refs": [{"type": "content", "value": content}],
            "max_summary_tokens": max_tokens
        })
        return r.json()

if __name__ == "__main__":
    server.run()
```

## Files to Delete

```
localagent/
├── policies.py          # DELETE
├── prompt_engine.py     # DELETE
├── subagents/
│   └── bash_runner.py   # DELETE
tests/
├── test_bash_runner.py  # DELETE
docs/
└── bash-runner-security.md  # DELETE
```

## Files to Simplify

### broker.py
- Remove: session management, retry queue, bash_runner dispatch
- Keep: /delegate, /health, file_scanner dispatch, summarizer dispatch

### schemas.py
- Remove: PolicyId, BashResult, QueuedTask
- Keep: DelegationRequest, DelegationResponse, ScanResult, SummarizeResult

## Estimated Final Size

| Before | After |
|--------|-------|
| 3,685 lines | ~800 lines |
| 22 files | ~10 files |
| 5 dependencies | 3 dependencies (fastapi, httpx, pydantic) |

## Acceptance Criteria

- [ ] `curl POST /delegate` with file_scanner works
- [ ] `curl POST /delegate` with summarizer works
- [ ] Cache hit skips Ollama call
- [ ] MCP server registers 2 tools: scan_files, summarize_file
- [ ] Total broker code < 300 lines
- [ ] Total MCP server code < 50 lines

---

## Startup (After Refactor)

```bash
# Terminal 1: Ollama
ollama serve

# Terminal 2: Broker
cd ~/dev/LocalAgent
source .venv/bin/activate
uvicorn localagent.broker:app --port 8000

# Terminal 3: MCP Server (optional, for Claude integration)
cd ~/dev/LocalAgent
python -m mcp_localagent.server
```

## Claude Usage (After MCP Integration)

```
Claude: "Scan the CasaWealth project and tell me what it does"

→ Calls scan_files(["**/*.py"], "../CasaWealth")
→ Gets 200-token summary + file paths
→ Knows which files exist without reading them all
→ Uses normal Read tool only for files it needs to edit
```

---

*Priority: High - Current implementation is over-engineered for the use case*

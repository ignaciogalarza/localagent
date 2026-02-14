# LocalAgent MVP Test Results & Required Fixes

## Test Summary

Tested LocalAgent against the CasaWealth project to validate token-efficient orchestration.

### What Works ✅

| Component | Status | Notes |
|-----------|--------|-------|
| file_scanner | ✅ Working | Scans files, computes SHA256 hashes, returns summaries |
| HTTP broker | ✅ Working | /delegate, /health endpoints functional |
| SQLite cache | ✅ Working | Content-addressable storage with LRU eviction |
| Session tracking | ✅ Working | Sessions created and maintained |
| Ollama health check | ✅ Working | Detects Ollama availability |

### Test Results

**Scan 1: Full project (accidentally included .venv)**
```
Files: 3,226 | LOC: 1,260,786 | Status: Completed (too broad)
```

**Scan 2: Source files only**
```
Files: 16 | LOC: 2,889 | Status: Completed
Token savings: ~50KB raw → 200 tokens summary (~99% reduction)
```

**Scan 3: Config files**
```
Files: 7 | Found: pyproject.toml, CLAUDE.md, README.md, .mcp.json
Status: Completed
```

### What Needs Fixing ❌

#### 1. bash_runner Sandbox Permissions

**Error:**
```
bwrap: setting up uid map: Permission denied
```

**Cause:** User namespaces not enabled on the host system.

**Fix Options:**
```bash
# Option A: Enable unprivileged user namespaces (requires sudo)
sudo sysctl -w kernel.unprivileged_userns_clone=1

# Option B: Make it persistent
echo 'kernel.unprivileged_userns_clone=1' | sudo tee /etc/sysctl.d/99-userns.conf
sudo sysctl --system

# Option C: Run without sandbox (less secure, for development only)
# Modify bash_runner.py to default use_sandbox=False
```

#### 2. Summarizer Content Passing

**Error:**
```
Expecting value: line 1 column 1 (char 0)
```

**Cause:** Large file content with special characters breaks JSON encoding when passed via curl.

**Fix Required:**
- Add a `/delegate/file` endpoint that accepts file paths directly
- Or: Base64 encode content before sending
- Or: Use multipart form upload for large content

**Code location:** `localagent/broker.py` - add new endpoint

#### 3. File Scanner .venv Exclusion

**Issue:** Scanning `**/*.py` includes virtual environment files.

**Fix Required:**
- Add default exclusion patterns: `.venv/`, `node_modules/`, `__pycache__/`
- Or: Add `exclude_patterns` parameter to scan request

**Code location:** `localagent/subagents/file_scanner.py`

---

## Startup Commands

```bash
# Terminal 1: Start Ollama (if not already running)
ollama serve

# Terminal 2: Pull the model (first time only)
ollama pull mistral:7b-instruct-q4_0

# Terminal 3: Start the LocalAgent broker
cd ~/dev/LocalAgent
source .venv/bin/activate
uvicorn localagent.broker:app --port 8000

# Verify everything is running
curl http://localhost:8000/health
# Expected: {"broker":"healthy","ollama":"healthy","queue_depth":0,...}
```

## Example Usage

```bash
# Scan Python files in a project
curl -X POST http://localhost:8000/delegate \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "scan-001",
    "tool_name": "file_scanner",
    "input_refs": [
      {"type": "glob", "value": "/path/to/project/*.py"},
      {"type": "glob", "value": "/path/to/project/src/**/*.py"}
    ],
    "max_summary_tokens": 200,
    "policy_id": "default"
  }'

# Check broker health
curl http://localhost:8000/health

# List allowed bash commands (readonly policy)
# grep, cat, ls, find, wc, head, tail, tree, file, stat
```

## Architecture Reminder

```
Claude (high-level planner)
    │
    ▼ HTTP POST /delegate
┌─────────────────────────────────────┐
│  LocalAgent Broker (localhost:8000) │
│                                     │
│  ┌─────────────┐ ┌─────────────┐   │
│  │file_scanner │ │ summarizer  │   │
│  │ (glob+hash) │ │ (Ollama 7B) │   │
│  └─────────────┘ └─────────────┘   │
│  ┌─────────────┐ ┌─────────────┐   │
│  │bash_runner  │ │   cache     │   │
│  │ (bwrap)     │ │  (SQLite)   │   │
│  └─────────────┘ └─────────────┘   │
└─────────────────────────────────────┘
```

## Next Steps

1. [ ] Fix sandbox permissions or add fallback mode
2. [ ] Add `/delegate/file` endpoint for file-based summarization
3. [ ] Add exclusion patterns to file_scanner
4. [ ] Create MCP server wrapper so Claude can call broker directly
5. [ ] Add integration tests with mock Ollama responses

---

*Generated from LocalAgent MVP test session - 2026-02-14*

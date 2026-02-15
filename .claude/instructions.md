# LocalAgent Project Instructions

## MANDATORY: Use MCP Tools for File Operations

**DO NOT use Glob, Grep, or Task(Explore).** Use LocalAgent MCP tools instead.

## Quick Start (New Session)

### Step 1: Check if MCP tools are available

Look for these tools in your tool list:
- `mcp__localagent__scan_files`
- `mcp__localagent__summarize_file`

If you see them, skip to Step 3.

### Step 2: If MCP tools are NOT available

The broker must be running AND Claude Code must be restarted:

```bash
# Start the broker
cd /home/ignacio/dev/LocalAgent && source .venv/bin/activate && uvicorn localagent.broker:app --port 8000 &
```

Then tell the user: "Please restart Claude Code to load MCP tools. The broker is running."

### Step 3: Use MCP tools

**Scan files in any directory:**
```
mcp__localagent__scan_files(
  patterns=["**/*.py", "**/*.ts", "**/*.tsx"],
  root="/home/ignacio/dev/SomeProject",
  max_tokens=300
)
```

**Summarize a file:**
```
mcp__localagent__summarize_file(
  path="/path/to/file.py",
  max_tokens=200
)
```

## MCP Tool Reference

| Tool | Purpose | Parameters |
|------|---------|------------|
| `scan_files` | List files + summary | `patterns` (list), `root` (path), `max_tokens` (50-500) |
| `summarize_file` | Compress file content | `path` (file), `max_tokens` (50-500) |

**Auto-excludes:** `.venv`, `node_modules`, `__pycache__`, `.git`

## Why This Matters

| Approach | Token Cost |
|----------|------------|
| Built-in Explore agent | ~47,000 tokens |
| LocalAgent MCP tools | ~200 tokens |
| **Savings** | **99% reduction** |

## Fallback: Direct API (if MCP unavailable)

Only use this if MCP tools are not loaded:

```bash
curl -s http://localhost:8000/delegate -H "Content-Type: application/json" -d '{
  "task_id": "scan-001",
  "tool_name": "file_scanner",
  "root_dir": "/path/to/scan",
  "input_refs": [{"type": "glob", "value": "**/*.py"}],
  "max_summary_tokens": 300
}'
```

## Architecture

```
localagent/
  broker.py          # FastAPI server (port 8000)
  schemas.py         # Request/response models
  subagents/
    file_scanner.py  # Glob + hash + summarize
    summarizer.py    # Ollama LLM compression
mcp_localagent/
  server.py          # MCP server (exposes tools to Claude Code)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| MCP tools not in tool list | Restart Claude Code |
| Broker not responding | Run: `source .venv/bin/activate && uvicorn localagent.broker:app --port 8000 &` |
| Scanning wrong directory | Check `root` parameter is absolute path |

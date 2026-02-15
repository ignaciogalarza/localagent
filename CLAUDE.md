# LocalAgent Development

This is the LocalAgent source repository. For using LocalAgent in your own projects, run:

```bash
pip install localagent
cd /path/to/your/project
localagent init
```

## MCP Tools (for this repo)

### `smart_search` - Semantic Code Search
```
smart_search(query="how does indexing work", project="localagent")
```

### `scan_files` - File Pattern Scanning
```
scan_files(patterns=["*.py"], root="/home/ignacio/dev/LocalAgent")
```

### `summarize_file` - Single File Summary
```
summarize_file(path="/home/ignacio/dev/LocalAgent/localagent/cli.py")
```

## Architecture

```
localagent/
├── cli.py           # Click CLI: serve, index, search, init, mcp
├── broker.py        # FastAPI HTTP broker
├── cache.py         # SQLite artifact cache
├── schemas.py       # Pydantic models
├── indexer/
│   └── core.py      # ChromaDB indexing
└── subagents/
    ├── file_scanner.py
    ├── summarizer.py
    └── smart_searcher.py

mcp_localagent/
└── server.py        # MCP server exposing tools
```

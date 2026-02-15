# LocalAgent

Semantic code search with LLM summarization for Claude Code. Index your codebase and search it using natural language queries.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Smart Search**: Semantic code search using ChromaDB vector embeddings
- **LLM Summarization**: AI-generated summaries of search results via Ollama (optional)
- **MCP Integration**: Seamless Claude Code integration via Model Context Protocol
- **Token Efficient**: ~99% reduction compared to reading raw files
- **Incremental Indexing**: Only re-indexes changed files

## Installation

```bash
pip install git+https://github.com/ignaciogalarza/localagent.git
```

This installs all dependencies automatically (ChromaDB, FastAPI, Click, etc.).

### Optional: Ollama for Summarization

For AI-powered search summaries, install [Ollama](https://ollama.ai/):

```bash
# macOS/Linux
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull mistral:7b-instruct-q4_0
```

> **Note**: Smart search works without Ollama - you just won't get AI summaries.

## Quick Start

```bash
# 1. Go to your project
cd /path/to/your/project

# 2. Initialize LocalAgent (creates CLAUDE.md, .mcp.json, indexes project)
localagent init

# 3. Restart Claude Code to load MCP tools

# 4. Ask Claude: "search for authentication in myproject"
```

## CLI Commands

```bash
localagent init                    # Initialize in current project
localagent index                   # Re-index current project
localagent search "query"          # Semantic search
localagent collections             # List indexed projects
localagent serve                   # Start HTTP broker
localagent mcp                     # Run MCP server
localagent delete <project>        # Delete project index
```

### Examples

```bash
# Index with custom project name
localagent index --project myapp

# Search code only
localagent search "database connection" --type code

# Search with more results
localagent search "error handling" --top-k 10

# Search without LLM summary (faster, no Ollama needed)
localagent search "auth" --no-summary

# Force full re-index
localagent index --full
```

## MCP Tools for Claude

After `localagent init`, Claude Code has access to:

| Tool | Description |
|------|-------------|
| `smart_search` | Semantic search with AI summaries |
| `scan_files` | Glob pattern file scanning |
| `summarize_file` | Single file summarization |

```python
# Example usage in Claude
smart_search(query="how does caching work", project="myproject", top_k=5)
```

## How It Works

```
localagent init
    ├── Creates CLAUDE.md (MCP tool instructions)
    ├── Creates .mcp.json (MCP server config)
    └── Indexes project in ChromaDB

localagent search "query"
    ├── Searches ChromaDB vector embeddings
    ├── Returns top-k matching code chunks
    └── Summarizes results via Ollama (if available)
```

### Data Storage

```
~/.localagent/
├── chroma/                 # Vector database
│   └── index-manifest.json # File hash tracking
└── cache/
    └── cache.db            # Summary cache
```

## Development

```bash
git clone https://github.com/ignaciogalarza/localagent.git
cd localagent
pip install -e ".[dev]"
pytest -v
```

## Token Efficiency

| Scenario | Raw Read | Smart Search | Savings |
|----------|----------|--------------|---------|
| Find auth code (500 files) | ~100K tokens | ~800 tokens | 99% |
| Understand caching | ~15K tokens | ~400 tokens | 97% |
| Explore new codebase | ~50K tokens | ~600 tokens | 99% |

## New Project Setup

Complete setup for a new project:

```bash
cd ~/dev/myproject
python3 -m venv .venv && source .venv/bin/activate
pip install git+https://github.com/ignaciogalarza/localagent.git
localagent init
```

Then restart Claude Code to load the MCP tools.

## Updating

Update LocalAgent in an existing project:

```bash
pip install --upgrade git+https://github.com/ignaciogalarza/localagent.git
localagent init --force
```

The `--force` flag updates the CLAUDE.md instructions to the latest version.

## License

MIT

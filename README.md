# LocalAgent

Semantic code search with LLM summarization for Claude Code. Index your codebase and search it using natural language queries.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- **Smart Search**: Semantic code search using ChromaDB vector embeddings
- **LLM Summarization**: AI-generated summaries of search results via Ollama
- **MCP Integration**: Seamless Claude Code integration via Model Context Protocol
- **Token Efficient**: ~99% reduction compared to reading raw files
- **Incremental Indexing**: Only re-indexes changed files

## Installation

```bash
pip install git+https://github.com/ignaciogalarza/localagent.git
```

Or for development:

```bash
git clone https://github.com/ignaciogalarza/localagent.git
cd localagent
pip install -e ".[dev]"
```

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) with Mistral model (for summarization)

```bash
# Install Ollama model
ollama pull mistral:7b-instruct-q4_0
```

## Quick Start

### Initialize in Your Project

```bash
cd /path/to/your/project
localagent init
```

This creates:
- `CLAUDE.md` - Instructions for Claude about available MCP tools
- `.mcp.json` - MCP server configuration
- Indexes your project for semantic search

### Restart Claude Code

After running `localagent init`, restart Claude Code to load the MCP tools.

### Use Smart Search

In Claude Code, ask naturally:
> "Search for how authentication works"

Or use the CLI:
```bash
localagent search "authentication implementation"
```

## CLI Commands

```bash
localagent init                    # Initialize in current project
localagent index                   # Re-index current project
localagent search "query"          # Semantic search
localagent collections             # List indexed projects
localagent serve                   # Start HTTP broker
localagent mcp                     # Run MCP server
```

### Examples

```bash
# Index a project with custom name
localagent index --project myapp --dir /path/to/project

# Search with options
localagent search "database connection" --top-k 10 --type code

# Force full re-index
localagent index --full

# Search without LLM summary (faster)
localagent search "error handling" --no-summary
```

## MCP Tools

When initialized, Claude Code has access to these tools:

| Tool | Description |
|------|-------------|
| `smart_search` | Semantic search with AI summaries |
| `scan_files` | Glob pattern file scanning |
| `summarize_file` | Single file summarization |

### smart_search

```python
smart_search(
    query="how does caching work",
    project="myproject",      # optional
    collection="code",        # "code", "docs", or None for both
    top_k=5                   # number of results
)
```

## Architecture

```
~/.localagent/
├── chroma/                 # Vector database (ChromaDB)
│   └── index-manifest.json # File hash tracking
└── cache/
    └── cache.db            # Summary cache (SQLite)
```

### Components

- **Indexer**: Chunks code files, stores embeddings in ChromaDB
- **Smart Searcher**: Queries vectors, summarizes results via Ollama
- **MCP Server**: Exposes tools to Claude Code
- **HTTP Broker**: Optional REST API for direct access

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# Run with coverage
pytest --cov=localagent

# Linting
ruff check localagent/

# Type checking
mypy localagent/
```

## Token Efficiency

| Scenario | Raw Read | Smart Search | Savings |
|----------|----------|--------------|---------|
| Find auth code (500 files) | ~100K tokens | ~800 tokens | 99% |
| Understand caching | ~15K tokens | ~400 tokens | 97% |
| Explore new codebase | ~50K tokens | ~600 tokens | 99% |

## License

MIT

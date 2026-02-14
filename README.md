# LocalAgent

A prototype orchestration system where Claude acts as a high-level planner delegating mechanical tasks to local subagents via a minimal HTTP broker.

## Features

- **File Scanner**: Glob pattern matching, content extraction, SHA256 hashing
- **Summarizer**: Content compression using local Mistral-7B via Ollama
- **Bash Runner**: Sandboxed command execution via bubblewrap
- **Artifact Cache**: Content-addressable SQLite cache with LRU eviction
- **Token Efficiency**: ~80% reduction via caching and 200-token summary limits

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) with Mistral-7B model
- [bubblewrap](https://github.com/containers/bubblewrap) (for sandboxed bash)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourorg/localagent.git
cd localagent

# Install dependencies
pip install -e ".[dev]"

# Pull the Ollama model
ollama pull mistral:7b-instruct-q4_0
```

### Running the Broker

```bash
# Start Ollama (if not already running)
ollama serve &

# Start the broker
uvicorn localagent.broker:app --port 8000
```

### Example Usage

#### File Scanner

```bash
curl -X POST http://localhost:8000/delegate \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "scan-001",
    "tool_name": "file_scanner",
    "input_refs": [{"type": "glob", "value": "**/*.py"}],
    "max_summary_tokens": 200,
    "policy_id": "default"
  }'
```

#### Summarizer

```bash
curl -X POST http://localhost:8000/delegate \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "sum-001",
    "tool_name": "summarizer",
    "input_refs": [{"type": "content", "value": "Long content to summarize..."}],
    "max_summary_tokens": 200,
    "policy_id": "default"
  }'
```

#### Bash Runner

```bash
curl -X POST http://localhost:8000/delegate \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "bash-001",
    "tool_name": "bash_runner",
    "input_refs": [{"type": "command", "value": "ls -la"}],
    "max_summary_tokens": 200,
    "policy_id": "readonly"
  }'
```

#### Health Check

```bash
curl http://localhost:8000/health
```

## API Reference

### POST /delegate

Delegate a task to a subagent.

**Request Body:**
```json
{
  "task_id": "string",
  "tool_name": "file_scanner|summarizer|bash_runner",
  "input_refs": [{"type": "glob|content|command|hash", "value": "string"}],
  "max_summary_tokens": 200,
  "policy_id": "default|readonly|build",
  "session_id": "optional-session-id"
}
```

**Response:**
```json
{
  "task_id": "string",
  "status": "completed|failed|partial|queued",
  "summary": "string (≤200 tokens)",
  "result_refs": [{"type": "file|cache|memory", "hash": "sha256:...", "path": "..."}],
  "confidence": 0.0-1.0,
  "audit_log_hashes": ["sha256:..."],
  "session_id": "string"
}
```

### POST /fetch_detail

Fetch full content for a result reference (hybrid delegation).

### GET /health

Check broker and dependency health.

## Policies

| Policy | Concurrency | Bash Commands |
|--------|-------------|---------------|
| `default` | Parallel (4) | Read-only: grep, cat, ls, find, etc. |
| `readonly` | Parallel (4) | Read-only commands only |
| `build` | Sequential | Read-only + make, npm run, pytest, etc. |

## Development

```bash
# Run tests
pytest -v

# Run with coverage
pytest --cov=localagent --cov-report=term-missing

# Run linting
ruff check localagent/

# Run type checking
mypy localagent/
```

## Architecture

See [docs/adr-001-architecture.md](docs/adr-001-architecture.md) for detailed architecture decisions.

## Security

See [docs/bash-runner-security.md](docs/bash-runner-security.md) for bash runner security model.

## License

MIT

# MCP Tools Guide

## What is MCP?

MCP (Model Context Protocol) is a standard that lets AI assistants like Claude connect to external tools. Think of it like plugins for Claude - they extend what Claude can do.

When you run `localagent init`, it configures Claude Code to automatically load LocalAgent's tools. After restarting Claude Code, these tools become available and Claude uses them when relevant.

## How It Works

```
You ask Claude a question
        ↓
Claude decides if a tool would help
        ↓
Claude calls the tool automatically
        ↓
Tool returns results to Claude
        ↓
Claude uses results to answer you
```

You don't need to explicitly ask Claude to use tools. Just ask questions naturally:

- "How does authentication work in this project?"
- "Find where errors are handled"
- "What files deal with database connections?"

Claude will automatically use `smart_search` to find relevant code and summarize it for you.

## Available Tools

### smart_search

**What it does**: Searches your codebase using natural language and returns relevant code snippets with AI-generated summaries.

**When Claude uses it**: When you ask about how something works, where something is implemented, or want to understand code.

**Example conversation**:
```
You: "How does caching work in this project?"

Claude: [automatically calls smart_search("how does caching work")]

Claude: "Based on the code, caching is implemented in cache.py using
        SQLite. The Cache class stores results with content hashes
        as keys. Here are the relevant files:
        - localagent/cache.py:15-45 (main Cache class)
        - localagent/subagents/summarizer.py:23 (cache usage)"
```

**Parameters**:
| Parameter | Description | Default |
|-----------|-------------|---------|
| `query` | Natural language search query | required |
| `project` | Project name to search | current directory |
| `collection` | "code", "docs", or both | both |
| `top_k` | Number of results | 5 |

### scan_files

**What it does**: Lists files matching glob patterns with a summary of what was found.

**When Claude uses it**: When you ask about project structure, want to see what files exist, or need to find files by pattern.

**Example conversation**:
```
You: "What Python files are in the subagents folder?"

Claude: [automatically calls scan_files(["subagents/*.py"])]

Claude: "The subagents folder contains 3 Python files:
        - file_scanner.py - scans directories for files
        - summarizer.py - generates summaries via Ollama
        - smart_searcher.py - semantic search implementation"
```

**Parameters**:
| Parameter | Description | Default |
|-----------|-------------|---------|
| `patterns` | List of glob patterns | required |
| `root` | Root directory to search | required |
| `max_tokens` | Max tokens for summary | 200 |

### summarize_file

**What it does**: Reads a single file and generates an AI summary of its contents.

**When Claude uses it**: When you want to understand what a specific file does without reading all the code.

**Example conversation**:
```
You: "What does broker.py do?"

Claude: [automatically calls summarize_file("localagent/broker.py")]

Claude: "broker.py implements a FastAPI HTTP server that acts as a
        task broker. It has endpoints for delegating tasks to
        subagents and retrieving results. The main endpoint is
        POST /delegate which routes tasks to file_scanner or
        summarizer based on the tool_name parameter."
```

**Parameters**:
| Parameter | Description | Default |
|-----------|-------------|---------|
| `path` | Absolute path to file | required |
| `max_tokens` | Max tokens for summary | 200 |

## Why Use These Tools?

### Token Efficiency

Reading files directly uses many tokens. These tools are much more efficient:

| Task | Reading Files | Using Tools | Savings |
|------|---------------|-------------|---------|
| Find auth implementation | ~100K tokens | ~800 tokens | 99% |
| Understand a module | ~15K tokens | ~400 tokens | 97% |
| Explore new codebase | ~50K tokens | ~600 tokens | 99% |

### Better Answers

The tools provide:
- **Relevant results**: Semantic search finds conceptually related code, not just keyword matches
- **Context**: AI summaries explain what code does, not just where it is
- **Efficiency**: Get answers faster without Claude reading entire files

## Tips for Best Results

1. **Ask naturally**: Don't try to phrase things like search queries. Just ask what you want to know.

2. **Be specific**: "How does user authentication work?" is better than "auth"

3. **Trust Claude**: Let Claude decide when to use tools. It knows when searching will help.

4. **Index after changes**: Run `localagent index` after making significant code changes to keep the search up to date.

## Troubleshooting

### Tools not appearing in Claude

1. Make sure you ran `localagent init`
2. Restart Claude Code completely
3. Check that `.mcp.json` exists in your project

### Search returns no results

1. Run `localagent collections` to verify your project is indexed
2. Run `localagent index` to re-index
3. Try broader search terms

### Summaries not working

Summaries require Ollama. If not installed, searches still work but return matches without AI summaries. Install Ollama:

```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull mistral:7b-instruct-q4_0
```

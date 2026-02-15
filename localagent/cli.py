"""CLI for LocalAgent - semantic code search and MCP server."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="localagent")
def main() -> None:
    """LocalAgent - Semantic code search with LLM summarization.

    Index your codebase and search it using natural language queries.
    """
    pass


@main.command()
@click.option("--port", default=8000, help="Port to run the broker on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def serve(port: int, host: str, reload: bool) -> None:
    """Start the LocalAgent HTTP broker server."""
    import uvicorn

    click.echo(f"Starting LocalAgent broker on {host}:{port}")
    uvicorn.run(
        "localagent.broker:app",
        host=host,
        port=port,
        reload=reload,
    )


@main.command()
@click.option(
    "--project", "-p",
    default=None,
    help="Project name for the index (defaults to directory name)",
)
@click.option(
    "--full", "-f",
    is_flag=True,
    help="Force full reindex (ignore manifest)",
)
@click.option(
    "--dir", "-d",
    "directory",
    default=".",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    help="Directory to index (defaults to current directory)",
)
def index(project: str | None, full: bool, directory: str) -> None:
    """Index a directory for semantic search.

    Scans the directory for code and documentation files, chunks them,
    and stores them in ChromaDB for semantic search.

    \b
    Example:
        localagent index --project myapp
        localagent index --project myapp --full
        localagent index --dir /path/to/repo
    """
    from localagent.indexer import get_indexer

    root = Path(directory).resolve()
    project_name = project or root.name

    click.echo(f"Indexing {root} as project '{project_name}'...")
    if full:
        click.echo("Full reindex requested - clearing existing data")

    indexer = get_indexer()
    stats = indexer.index_directory(
        root=root,
        project=project_name,
        full_reindex=full,
    )

    click.echo(f"Done! Indexed: {stats['indexed']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")


@main.command()
@click.argument("query")
@click.option(
    "--project", "-p",
    default=None,
    help="Project name to search (defaults to current directory name)",
)
@click.option(
    "--top-k", "-k",
    default=5,
    help="Number of results to return",
)
@click.option(
    "--type", "-t",
    "collection_type",
    type=click.Choice(["docs", "code", "all"]),
    default="all",
    help="Collection type to search",
)
@click.option(
    "--no-summary",
    is_flag=True,
    help="Skip LLM summarization",
)
@click.option(
    "--raw",
    is_flag=True,
    help="Output raw JSON instead of formatted text",
)
def search(
    query: str,
    project: str | None,
    top_k: int,
    collection_type: str,
    no_summary: bool,
    raw: bool,
) -> None:
    """Search the index using natural language.

    \b
    Example:
        localagent search "how does caching work"
        localagent search "authentication" --project myapp --top-k 10
    """
    from localagent.subagents.smart_searcher import smart_search

    project_name = project or Path.cwd().name
    coll_type = None if collection_type == "all" else collection_type

    result = smart_search(
        query=query,
        project_name=project_name,
        collection_type=coll_type,
        top_k=top_k,
        summarize=not no_summary,
    )

    if raw:
        import json
        click.echo(json.dumps(result.model_dump(), indent=2))
        return

    # Formatted output
    click.echo(f"\n{'=' * 60}")
    click.echo(f"Search: {query}")
    click.echo(f"Project: {project_name} | Collection: {result.collection_searched}")
    click.echo(f"{'=' * 60}\n")

    if result.matches:
        click.echo(f"Found {result.total_matches} matches:\n")
        for i, match in enumerate(result.matches, 1):
            start = match.metadata.get("start_line", "?")
            end = match.metadata.get("end_line", "?")
            click.echo(f"  {i}. {match.file_path}:{start}-{end} (distance: {match.distance:.3f})")

        click.echo(f"\n{'─' * 60}")
        click.echo("Summary:")
        click.echo(f"{'─' * 60}")
        click.echo(result.summary)
        click.echo()
    else:
        click.echo("No matches found.")


@main.command()
def mcp() -> None:
    """Run the MCP server for Claude integration.

    This command starts the MCP server which exposes LocalAgent tools
    to Claude Code via the Model Context Protocol.

    \b
    Configure in .mcp.json:
        {
            "mcpServers": {
                "localagent": {
                    "command": "localagent",
                    "args": ["mcp"]
                }
            }
        }
    """
    # Import and run the MCP server
    from mcp_localagent.server import mcp as mcp_server
    mcp_server.run()


@main.command()
def collections() -> None:
    """List all indexed collections."""
    from localagent.indexer import get_indexer

    indexer = get_indexer()
    collections = indexer.list_collections()

    if collections:
        click.echo("Indexed collections:")
        for name in sorted(collections):
            click.echo(f"  - {name}")
    else:
        click.echo("No collections found. Run 'localagent index' to create one.")


@main.command()
@click.argument("project")
@click.confirmation_option(prompt="Are you sure you want to delete this project's index?")
def delete(project: str) -> None:
    """Delete a project's index.

    \b
    Example:
        localagent delete myapp
    """
    from localagent.indexer import get_indexer

    indexer = get_indexer()
    indexer.delete_project(project)
    click.echo(f"Deleted index for project: {project}")


# Template for CLAUDE.md instructions
CLAUDE_MD_TEMPLATE = '''# LocalAgent - Semantic Code Search

This project uses LocalAgent for semantic code search via MCP tools.

## Available MCP Tools

### `smart_search` - Semantic Code Search
Search the indexed codebase using natural language. Returns relevant code chunks with AI summaries.

```
smart_search(query="how does authentication work", project="{project}", top_k=5)
```

**Parameters:**
- `query`: Natural language search (e.g., "database connection", "error handling")
- `project`: Project name (default: "{project}")
- `collection`: "docs", "code", or null for both
- `top_k`: Number of results (default: 5)

**Use smart_search instead of reading files when exploring code** - it's 99% more token-efficient.

### `scan_files` - File Pattern Scanning
```
scan_files(patterns=["*.py"], root="/path/to/project")
```

### `summarize_file` - Single File Summary
```
summarize_file(path="/absolute/path/to/file.py")
```

## Quick Reference

| Task | Tool |
|------|------|
| Find where X is implemented | `smart_search(query="X implementation")` |
| Understand how Y works | `smart_search(query="how does Y work")` |
| List project files | `scan_files(patterns=["**/*.py"])` |
| Summarize one file | `summarize_file(path="...")` |
'''


@main.command()
@click.option(
    "--project", "-p",
    default=None,
    help="Project name (defaults to directory name)",
)
@click.option(
    "--no-index",
    is_flag=True,
    help="Skip initial indexing",
)
def init(project: str | None, no_index: bool) -> None:
    """Initialize LocalAgent in a project.

    Creates CLAUDE.md with MCP tool instructions, sets up .mcp.json,
    and optionally indexes the project.

    \b
    Example:
        cd /path/to/myproject
        localagent init
        localagent init --project myapp --no-index
    """
    import json
    import shutil

    cwd = Path.cwd()
    project_name = project or cwd.name

    # 1. Create/update CLAUDE.md
    claude_md_path = cwd / "CLAUDE.md"
    localagent_section = CLAUDE_MD_TEMPLATE.format(project=project_name)

    if claude_md_path.exists():
        existing = claude_md_path.read_text()
        if "LocalAgent" in existing and "smart_search" in existing:
            click.echo("CLAUDE.md already has LocalAgent instructions, skipping...")
        else:
            # Append to existing CLAUDE.md
            with open(claude_md_path, "a") as f:
                f.write("\n\n" + localagent_section)
            click.echo("Updated CLAUDE.md with LocalAgent instructions")
    else:
        claude_md_path.write_text(localagent_section)
        click.echo("Created CLAUDE.md with LocalAgent instructions")

    # 2. Create/update .mcp.json
    mcp_json_path = cwd / ".mcp.json"
    localagent_executable = shutil.which("localagent") or "localagent"

    localagent_config = {
        "command": localagent_executable,
        "args": ["mcp"],
    }

    if mcp_json_path.exists():
        try:
            mcp_config = json.loads(mcp_json_path.read_text())
        except json.JSONDecodeError:
            mcp_config = {"mcpServers": {}}
    else:
        mcp_config = {"mcpServers": {}}

    if "mcpServers" not in mcp_config:
        mcp_config["mcpServers"] = {}

    if "localagent" in mcp_config["mcpServers"]:
        click.echo(".mcp.json already has localagent config, skipping...")
    else:
        mcp_config["mcpServers"]["localagent"] = localagent_config
        mcp_json_path.write_text(json.dumps(mcp_config, indent=2) + "\n")
        click.echo("Updated .mcp.json with localagent MCP server")

    # 3. Index the project (unless --no-index)
    if not no_index:
        click.echo(f"\nIndexing project '{project_name}'...")
        from localagent.indexer import get_indexer

        indexer = get_indexer()
        stats = indexer.index_directory(
            root=cwd,
            project=project_name,
            full_reindex=False,
        )
        click.echo(f"Indexed: {stats['indexed']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")

    click.echo(f"\n✓ LocalAgent initialized for '{project_name}'")
    click.echo("\nNext steps:")
    click.echo("  1. Restart Claude Code to load MCP tools")
    click.echo(f"  2. Ask Claude: 'search for X in {project_name}'")


if __name__ == "__main__":
    main()

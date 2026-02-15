"""MCP server exposing LocalAgent tools to Claude."""

from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("localagent")
BROKER = "http://localhost:8000"


@mcp.tool()
async def scan_files(patterns: list[str], root: str, max_tokens: int = 200) -> dict:
    """Scan files matching glob patterns. Returns file list + summary.

    Auto-excludes: .venv, node_modules, __pycache__, .git
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{BROKER}/delegate", json={
            "task_id": f"scan-{hash(tuple(patterns)) & 0xFFFFFF:06x}",
            "tool_name": "file_scanner",
            "input_refs": [{"type": "glob", "value": p} for p in patterns],
            "root_dir": root,
            "max_summary_tokens": max_tokens,
        })
        return r.json()


@mcp.tool()
async def summarize_file(path: str, max_tokens: int = 200) -> dict:
    """Summarize a file's content via Ollama. Cached by content hash."""
    content = open(path).read()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{BROKER}/delegate", json={
            "task_id": f"sum-{hash(path) & 0xFFFFFF:06x}",
            "tool_name": "summarizer",
            "input_refs": [{"type": "content", "value": content}],
            "max_summary_tokens": max_tokens,
        })
        return r.json()


@mcp.tool()
async def smart_search(
    query: str,
    project: str | None = None,
    collection: str | None = None,
    top_k: int = 5,
) -> dict:
    """Semantic search across indexed codebase with LLM summarization.

    Args:
        query: Natural language search query
        project: Project name (defaults to 'localagent')
        collection: Collection type - 'docs', 'code', or None for both
        top_k: Number of results to return

    Returns:
        Search results with matches and AI-generated summary
    """
    from localagent.subagents.smart_searcher import smart_search as do_search

    project_name = project or "localagent"

    result = do_search(
        query=query,
        project_name=project_name,
        collection_type=collection,
        top_k=top_k,
        summarize=True,
    )

    return result.model_dump()


if __name__ == "__main__":
    mcp.run()

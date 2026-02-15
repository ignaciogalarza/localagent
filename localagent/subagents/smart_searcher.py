"""Smart searcher subagent for semantic search with LLM summarization."""

from __future__ import annotations

import logging
from typing import Any

from localagent.indexer import get_indexer
from localagent.schemas import SearchMatch, SmartSearchResult
from localagent.subagents.summarizer import summarize_content

logger = logging.getLogger(__name__)

# Default settings
DEFAULT_TOP_K = 5
DEFAULT_MAX_SUMMARY_TOKENS = 200


def _estimate_tokens(text: str) -> int:
    """Estimate token count using word-based heuristic."""
    return int(len(text.split()) * 1.33)


def _format_matches_for_summary(matches: list[dict[str, Any]], query: str) -> str:
    """Format search matches into a prompt for summarization."""
    parts = [f"Query: {query}\n\nRelevant code/documentation snippets:\n"]

    for i, match in enumerate(matches, 1):
        metadata = match.get("metadata", {})
        file_path = metadata.get("file_path", "unknown")
        start_line = metadata.get("start_line", "?")
        end_line = metadata.get("end_line", "?")
        content = match.get("content", "")

        # Truncate long content
        if len(content) > 1000:
            content = content[:1000] + "..."

        parts.append(f"\n--- Match {i}: {file_path} (lines {start_line}-{end_line}) ---\n")
        parts.append(content)

    return "\n".join(parts)


def smart_search(
    query: str,
    project_name: str = "localagent",
    collection_type: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    summarize: bool = True,
    max_summary_tokens: int = DEFAULT_MAX_SUMMARY_TOKENS,
) -> SmartSearchResult:
    """Perform semantic search with optional LLM summarization.

    Args:
        query: Natural language search query
        project_name: Name of the indexed project
        collection_type: 'docs', 'code', or None for both
        top_k: Number of results to return
        summarize: Whether to generate an LLM summary
        max_summary_tokens: Maximum tokens in summary

    Returns:
        SmartSearchResult with matches and summary
    """
    logger.info(f"Smart search: query='{query}', project={project_name}, top_k={top_k}")

    # Get indexer and search
    indexer = get_indexer()
    raw_matches = indexer.search(
        query=query,
        project=project_name,
        collection_type=collection_type,
        top_k=top_k,
    )

    # Convert to SearchMatch objects
    matches = [
        SearchMatch(
            file_path=m.get("metadata", {}).get("file_path", "unknown"),
            chunk_content=m.get("content", ""),
            distance=m.get("distance", 0.0),
            metadata={
                "start_line": m.get("metadata", {}).get("start_line"),
                "end_line": m.get("metadata", {}).get("end_line"),
                "extension": m.get("metadata", {}).get("extension"),
                "collection_type": m.get("collection_type"),
            },
        )
        for m in raw_matches
    ]

    # Determine collection searched
    collection_searched = collection_type or "all"
    if raw_matches:
        types_found = set(m.get("collection_type") for m in raw_matches)
        if len(types_found) == 1:
            collection_searched = types_found.pop()

    # Generate summary if requested and matches found
    if summarize and matches:
        context = _format_matches_for_summary(raw_matches, query)
        summary_result = summarize_content(
            content=context,
            max_tokens=max_summary_tokens,
            context=f"Summarize the search results for query: {query}",
        )
        summary = summary_result.summary
        summary_tokens = summary_result.token_count
        confidence = summary_result.confidence
    elif matches:
        # No summarization, provide basic summary
        file_paths = list(set(m.file_path for m in matches))
        summary = f"Found {len(matches)} matches in {len(file_paths)} files: {', '.join(file_paths[:3])}"
        if len(file_paths) > 3:
            summary += f" and {len(file_paths) - 3} more"
        summary_tokens = _estimate_tokens(summary)
        confidence = 0.7
    else:
        summary = f"No matches found for query: {query}"
        summary_tokens = _estimate_tokens(summary)
        confidence = 1.0  # Confident there are no matches

    return SmartSearchResult(
        query=query,
        matches=matches,
        summary=summary,
        summary_token_count=summary_tokens,
        confidence=confidence,
        collection_searched=collection_searched,
        total_matches=len(matches),
    )

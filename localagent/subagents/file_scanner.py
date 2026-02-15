"""File scanner subagent for glob pattern matching and content extraction."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from localagent.schemas import ResultRef, ResultRefType, ScanResult

logger = logging.getLogger(__name__)

# Default exclusion patterns
DEFAULT_EXCLUDES = {".venv", "node_modules", "__pycache__", ".git", ".tox", "dist", "build"}

# Binary file detection: check for null bytes in first 8KB
BINARY_CHECK_SIZE = 8192

# Maximum file size to read fully (50KB)
MAX_FILE_SIZE = 50 * 1024


def _compute_sha256(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _is_binary(content: bytes) -> bool:
    """Check if content appears to be binary (contains null bytes)."""
    return b"\x00" in content[:BINARY_CHECK_SIZE]


def _is_excluded(file_path: Path) -> bool:
    """Check if file is in an excluded directory."""
    return any(excl in file_path.parts for excl in DEFAULT_EXCLUDES)


def _estimate_tokens(text: str) -> int:
    """Estimate token count using simple word-based heuristic.

    Rough approximation: 1 token ≈ 0.75 words for code/technical content.
    """
    words = len(text.split())
    return int(words * 1.33)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    words = text.split()
    # Approximate: 0.75 words per token, so max_words ≈ max_tokens * 0.75
    max_words = int(max_tokens * 0.75)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def scan_files(
    patterns: list[str],
    root_dir: str,
    max_summary_tokens: int = 200,
) -> ScanResult:
    """Scan files matching glob patterns and return structured results.

    Args:
        patterns: List of glob patterns (e.g., ["*.py", "**/*.md"])
        root_dir: Root directory to search from
        max_summary_tokens: Maximum tokens in the summary

    Returns:
        ScanResult with summary, result_refs, and metadata
    """
    root = Path(root_dir)
    if not root.exists():
        logger.warning(f"Root directory does not exist: {root_dir}")
        return ScanResult(
            summary=f"Directory not found: {root_dir}",
            summary_token_count=5,
            result_refs=[],
            confidence=1.0,
            files_scanned=0,
            total_bytes=0,
        )

    matched_files: list[tuple[Path, bytes, str]] = []  # (path, content, hash)
    skipped_binary: list[Path] = []
    skipped_permission: list[Path] = []
    total_bytes = 0

    for pattern in patterns:
        for file_path in root.glob(pattern):
            if not file_path.is_file():
                continue

            if _is_excluded(file_path):
                continue

            try:
                content = file_path.read_bytes()

                # Skip binary files
                if _is_binary(content):
                    skipped_binary.append(file_path)
                    logger.debug(f"Skipped binary file: {file_path}")
                    continue

                content_hash = _compute_sha256(content)
                matched_files.append((file_path, content, content_hash))
                total_bytes += len(content)

            except PermissionError:
                skipped_permission.append(file_path)
                logger.warning(f"Permission denied: {file_path}")
            except Exception as e:
                logger.error(f"Error reading {file_path}: {e}")

    # Build result refs
    result_refs = [
        ResultRef(
            type=ResultRefType.FILE,
            path=str(file_path.relative_to(root)),
            hash=content_hash,
            size_bytes=len(content),
        )
        for file_path, content, content_hash in matched_files
    ]

    # Build summary
    if not matched_files:
        summary = f"No files matched patterns {patterns} in {root_dir}"
        if skipped_binary:
            summary += f". Skipped {len(skipped_binary)} binary files."
        if skipped_permission:
            summary += f". {len(skipped_permission)} files had permission errors."
    else:
        # Group files by extension for summary
        ext_counts: dict[str, int] = {}
        ext_lines: dict[str, int] = {}

        for file_path, content, _ in matched_files:
            ext = file_path.suffix or "no-ext"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            try:
                line_count = content.decode("utf-8", errors="replace").count("\n")
                ext_lines[ext] = ext_lines.get(ext, 0) + line_count
            except Exception:
                pass

        # Build concise summary
        parts = [f"Scanned {len(matched_files)} files in {root_dir}"]

        # Add breakdown by type
        type_info = []
        for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1])[:5]:
            lines = ext_lines.get(ext, 0)
            type_info.append(f"{ext}: {count} files, {lines} LOC")

        if type_info:
            parts.append("Breakdown: " + "; ".join(type_info))

        # Add notable files (largest by size)
        if matched_files:
            sorted_by_size = sorted(matched_files, key=lambda x: len(x[1]), reverse=True)[:3]
            notable = [str(f[0].relative_to(root)) for f in sorted_by_size]
            parts.append(f"Largest files: {', '.join(notable)}")

        if skipped_binary:
            parts.append(f"Skipped {len(skipped_binary)} binary files")

        summary = ". ".join(parts) + "."

    # Truncate summary if needed
    summary = _truncate_to_tokens(summary, max_summary_tokens)
    summary_tokens = _estimate_tokens(summary)

    return ScanResult(
        summary=summary,
        summary_token_count=summary_tokens,
        result_refs=result_refs,
        confidence=1.0 if matched_files or not patterns else 0.8,
        files_scanned=len(matched_files),
        total_bytes=total_bytes,
    )

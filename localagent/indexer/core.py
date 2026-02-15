"""ChromaDB-based indexer for semantic code search."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
import pathspec

logger = logging.getLogger(__name__)

# Default data directory
DEFAULT_CHROMA_DIR = Path.home() / ".localagent" / "chroma"
DEFAULT_MANIFEST_PATH = Path.home() / ".localagent" / "chroma" / "index-manifest.json"

# Default exclusions (directories)
DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".tox",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    ".coverage",
    "*.egg-info",
}

# File extensions for docs vs code collections
DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".bash",
    ".zsh", ".sql", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
}

# Chunking settings
CHUNK_LINES = 200
CHUNK_OVERLAP = 50
MAX_FILE_SIZE = 500 * 1024  # 500KB


def _compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    """Load .gitignore patterns if present."""
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        try:
            patterns = gitignore_path.read_text().splitlines()
            return pathspec.PathSpec.from_lines("gitignore", patterns)
        except Exception as e:
            logger.warning(f"Failed to parse .gitignore: {e}")
    return None


def _should_exclude(path: Path, root: Path, gitignore: pathspec.PathSpec | None) -> bool:
    """Check if path should be excluded from indexing."""
    # Check default excludes
    for part in path.relative_to(root).parts:
        if part in DEFAULT_EXCLUDES:
            return True
        # Check wildcard patterns like *.egg-info
        for pattern in DEFAULT_EXCLUDES:
            if "*" in pattern:
                import fnmatch
                if fnmatch.fnmatch(part, pattern):
                    return True

    # Check gitignore
    if gitignore:
        rel_path = str(path.relative_to(root))
        if gitignore.match_file(rel_path):
            return True

    return False


def _chunk_content(content: str, file_path: str) -> list[dict[str, Any]]:
    """Split content into overlapping chunks.

    Returns list of dicts with 'content', 'start_line', 'end_line'.
    """
    lines = content.splitlines(keepends=True)
    chunks = []

    if len(lines) <= CHUNK_LINES:
        # Small file, single chunk
        chunks.append({
            "content": content,
            "start_line": 1,
            "end_line": len(lines),
            "file_path": file_path,
        })
    else:
        # Large file, create overlapping chunks
        start = 0
        while start < len(lines):
            end = min(start + CHUNK_LINES, len(lines))
            chunk_lines = lines[start:end]
            chunks.append({
                "content": "".join(chunk_lines),
                "start_line": start + 1,
                "end_line": end,
                "file_path": file_path,
            })

            # Move start forward, with overlap
            start = end - CHUNK_OVERLAP
            if start >= len(lines) - CHUNK_OVERLAP:
                break

    return chunks


class Indexer:
    """ChromaDB indexer for semantic code search."""

    def __init__(
        self,
        chroma_dir: Path | str | None = None,
        manifest_path: Path | str | None = None,
    ):
        """Initialize the indexer.

        Args:
            chroma_dir: Directory for ChromaDB storage
            manifest_path: Path to index manifest JSON
        """
        self.chroma_dir = Path(chroma_dir) if chroma_dir else DEFAULT_CHROMA_DIR
        self.manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH

        # Ensure directories exist
        self.chroma_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB with persistent storage
        self.client = chromadb.PersistentClient(
            path=str(self.chroma_dir),
            settings=Settings(anonymized_telemetry=False),
        )

        self._manifest: dict[str, dict[str, str]] = self._load_manifest()

    def _load_manifest(self) -> dict[str, dict[str, str]]:
        """Load the index manifest from disk."""
        if self.manifest_path.exists():
            try:
                return json.loads(self.manifest_path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load manifest: {e}")
        return {}

    def _save_manifest(self) -> None:
        """Save the index manifest to disk."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(self._manifest, indent=2))

    def _get_collection(self, project: str, collection_type: str) -> chromadb.Collection:
        """Get or create a collection for the project.

        Args:
            project: Project name
            collection_type: 'docs' or 'code'

        Returns:
            ChromaDB collection
        """
        collection_name = f"{project}-{collection_type}"
        return self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def index_directory(
        self,
        root: Path | str,
        project: str,
        full_reindex: bool = False,
    ) -> dict[str, int]:
        """Index a directory for semantic search.

        Args:
            root: Root directory to index
            project: Project name for collection naming
            full_reindex: If True, reindex all files regardless of hash

        Returns:
            Dict with 'indexed', 'skipped', 'errors' counts
        """
        root = Path(root).resolve()
        if not root.exists():
            raise ValueError(f"Directory does not exist: {root}")

        gitignore = _load_gitignore(root)

        # Get collections
        docs_collection = self._get_collection(project, "docs")
        code_collection = self._get_collection(project, "code")

        if full_reindex:
            # Clear existing data
            self._manifest.pop(project, None)
            try:
                self.client.delete_collection(f"{project}-docs")
                self.client.delete_collection(f"{project}-code")
            except Exception:
                pass
            docs_collection = self._get_collection(project, "docs")
            code_collection = self._get_collection(project, "code")

        project_manifest = self._manifest.setdefault(project, {})

        stats = {"indexed": 0, "skipped": 0, "errors": 0}

        # Find all files
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue

            if _should_exclude(file_path, root, gitignore):
                continue

            # Check file extension
            ext = file_path.suffix.lower()
            if ext not in DOC_EXTENSIONS and ext not in CODE_EXTENSIONS:
                continue

            # Check file size
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    logger.debug(f"Skipping large file: {file_path}")
                    stats["skipped"] += 1
                    continue
            except OSError:
                stats["errors"] += 1
                continue

            # Read and hash content
            try:
                content = file_path.read_bytes()
                if b"\x00" in content[:8192]:  # Binary file
                    stats["skipped"] += 1
                    continue

                content_str = content.decode("utf-8", errors="replace")
                file_hash = _compute_file_hash(content)
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                stats["errors"] += 1
                continue

            # Check if already indexed with same hash
            rel_path = str(file_path.relative_to(root))
            if rel_path in project_manifest and project_manifest[rel_path] == file_hash:
                stats["skipped"] += 1
                continue

            # Determine collection
            collection = docs_collection if ext in DOC_EXTENSIONS else code_collection

            # Chunk and index
            chunks = _chunk_content(content_str, rel_path)

            try:
                # Remove old chunks for this file
                existing_ids = collection.get(
                    where={"file_path": rel_path},
                    include=[],
                )
                if existing_ids["ids"]:
                    collection.delete(ids=existing_ids["ids"])

                # Add new chunks
                ids = [f"{rel_path}:{chunk['start_line']}" for chunk in chunks]
                documents = [chunk["content"] for chunk in chunks]
                metadatas = [
                    {
                        "file_path": chunk["file_path"],
                        "start_line": chunk["start_line"],
                        "end_line": chunk["end_line"],
                        "extension": ext,
                    }
                    for chunk in chunks
                ]

                collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                )

                project_manifest[rel_path] = file_hash
                stats["indexed"] += 1
                logger.debug(f"Indexed: {rel_path} ({len(chunks)} chunks)")

            except Exception as e:
                logger.error(f"Error indexing {file_path}: {e}")
                stats["errors"] += 1

        # Save manifest
        self._save_manifest()

        logger.info(
            f"Indexing complete: {stats['indexed']} indexed, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )

        return stats

    def search(
        self,
        query: str,
        project: str,
        collection_type: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search the index for relevant content.

        Args:
            query: Search query string
            project: Project name
            collection_type: 'docs', 'code', or None for both
            top_k: Number of results to return

        Returns:
            List of search results with content, metadata, and distance
        """
        results = []

        collections_to_search = []
        if collection_type == "docs" or collection_type is None:
            try:
                collections_to_search.append(
                    (self.client.get_collection(f"{project}-docs"), "docs")
                )
            except Exception:
                pass

        if collection_type == "code" or collection_type is None:
            try:
                collections_to_search.append(
                    (self.client.get_collection(f"{project}-code"), "code")
                )
            except Exception:
                pass

        for collection, coll_type in collections_to_search:
            try:
                query_results = collection.query(
                    query_texts=[query],
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"],
                )

                if query_results["documents"] and query_results["documents"][0]:
                    for i, doc in enumerate(query_results["documents"][0]):
                        results.append({
                            "content": doc,
                            "metadata": query_results["metadatas"][0][i] if query_results["metadatas"] else {},
                            "distance": query_results["distances"][0][i] if query_results["distances"] else 0.0,
                            "collection_type": coll_type,
                        })
            except Exception as e:
                logger.warning(f"Error searching {coll_type} collection: {e}")

        # Sort by distance and limit to top_k
        results.sort(key=lambda x: x["distance"])
        return results[:top_k]

    def list_collections(self) -> list[str]:
        """List all indexed collections."""
        return [c.name for c in self.client.list_collections()]

    def delete_project(self, project: str) -> None:
        """Delete all collections for a project."""
        try:
            self.client.delete_collection(f"{project}-docs")
        except Exception:
            pass
        try:
            self.client.delete_collection(f"{project}-code")
        except Exception:
            pass
        self._manifest.pop(project, None)
        self._save_manifest()


# Global indexer instance
_indexer_instance: Indexer | None = None


def get_indexer(
    chroma_dir: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> Indexer:
    """Get or create the global indexer instance.

    Args:
        chroma_dir: Optional ChromaDB directory
        manifest_path: Optional manifest path

    Returns:
        Indexer instance
    """
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = Indexer(chroma_dir=chroma_dir, manifest_path=manifest_path)
    return _indexer_instance

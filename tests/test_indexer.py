"""Tests for the indexer module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from localagent.indexer.core import (
    Indexer,
    _compute_file_hash,
    _should_exclude,
    _chunk_content,
    _load_gitignore,
    CHUNK_LINES,
)


class TestFileHash:
    """Test file hashing."""

    def test_compute_file_hash_deterministic(self):
        """Same content produces same hash."""
        content = b"test content"
        hash1 = _compute_file_hash(content)
        hash2 = _compute_file_hash(content)
        assert hash1 == hash2

    def test_compute_file_hash_different_content(self):
        """Different content produces different hash."""
        hash1 = _compute_file_hash(b"content1")
        hash2 = _compute_file_hash(b"content2")
        assert hash1 != hash2


class TestExclusions:
    """Test file exclusion logic."""

    def test_excludes_venv(self, tmp_path):
        """Excludes .venv directory."""
        venv_file = tmp_path / ".venv" / "lib" / "test.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.touch()
        assert _should_exclude(venv_file, tmp_path, None)

    def test_excludes_node_modules(self, tmp_path):
        """Excludes node_modules directory."""
        nm_file = tmp_path / "node_modules" / "pkg" / "index.js"
        nm_file.parent.mkdir(parents=True)
        nm_file.touch()
        assert _should_exclude(nm_file, tmp_path, None)

    def test_excludes_git(self, tmp_path):
        """Excludes .git directory."""
        git_file = tmp_path / ".git" / "config"
        git_file.parent.mkdir(parents=True)
        git_file.touch()
        assert _should_exclude(git_file, tmp_path, None)

    def test_does_not_exclude_normal_file(self, tmp_path):
        """Does not exclude normal files."""
        normal_file = tmp_path / "src" / "main.py"
        normal_file.parent.mkdir(parents=True)
        normal_file.touch()
        assert not _should_exclude(normal_file, tmp_path, None)

    def test_excludes_localagent_files(self, tmp_path):
        """Excludes LocalAgent's own files to avoid self-referential results."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.touch()
        assert _should_exclude(claude_md, tmp_path, None)

        mcp_json = tmp_path / ".mcp.json"
        mcp_json.touch()
        assert _should_exclude(mcp_json, tmp_path, None)


class TestGitignore:
    """Test gitignore parsing."""

    def test_load_gitignore_exists(self, tmp_path):
        """Loads gitignore when present."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\nbuild/\n")

        spec = _load_gitignore(tmp_path)
        assert spec is not None
        assert spec.match_file("debug.log")
        assert spec.match_file("build/output")

    def test_load_gitignore_not_exists(self, tmp_path):
        """Returns None when gitignore doesn't exist."""
        spec = _load_gitignore(tmp_path)
        assert spec is None

    def test_gitignore_integration(self, tmp_path):
        """Gitignore patterns exclude files."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n")

        spec = _load_gitignore(tmp_path)

        log_file = tmp_path / "app.log"
        log_file.touch()
        assert _should_exclude(log_file, tmp_path, spec)

        py_file = tmp_path / "app.py"
        py_file.touch()
        assert not _should_exclude(py_file, tmp_path, spec)


class TestChunking:
    """Test content chunking."""

    def test_small_file_single_chunk(self):
        """Small files produce single chunk."""
        content = "line1\nline2\nline3\n"
        chunks = _chunk_content(content, "test.py")

        assert len(chunks) == 1
        assert chunks[0]["content"] == content
        assert chunks[0]["start_line"] == 1
        assert chunks[0]["end_line"] == 3
        assert chunks[0]["file_path"] == "test.py"

    def test_large_file_multiple_chunks(self):
        """Large files produce multiple overlapping chunks."""
        lines = [f"line {i}\n" for i in range(CHUNK_LINES + 100)]
        content = "".join(lines)

        chunks = _chunk_content(content, "large.py")

        assert len(chunks) > 1
        assert chunks[0]["start_line"] == 1
        # Chunks should overlap
        assert chunks[1]["start_line"] < chunks[0]["end_line"]


class TestIndexer:
    """Test Indexer class."""

    @pytest.fixture
    def indexer(self, tmp_path):
        """Create indexer with temp storage."""
        chroma_dir = tmp_path / "chroma"
        manifest_path = tmp_path / "manifest.json"
        return Indexer(chroma_dir=chroma_dir, manifest_path=manifest_path)

    @pytest.fixture
    def sample_project(self, tmp_path):
        """Create a sample project structure."""
        project = tmp_path / "project"
        project.mkdir()

        # Python files
        (project / "main.py").write_text('"""Main module."""\n\ndef main():\n    pass\n')
        (project / "utils.py").write_text('"""Utils module."""\n\ndef helper():\n    return 42\n')

        # Docs
        (project / "README.md").write_text("# Project\n\nThis is a test project.\n")

        # Excluded directories
        venv = project / ".venv"
        venv.mkdir()
        (venv / "lib.py").write_text("# Should be excluded\n")

        return project

    def test_index_directory_creates_collections(self, indexer, sample_project):
        """Indexing creates docs and code collections."""
        stats = indexer.index_directory(sample_project, "test-project")

        collections = indexer.list_collections()
        assert "test-project-docs" in collections
        assert "test-project-code" in collections

    def test_index_directory_counts(self, indexer, sample_project):
        """Indexing returns correct counts."""
        stats = indexer.index_directory(sample_project, "test-project")

        # Should index main.py, utils.py, README.md (3 files)
        # .venv/lib.py should be excluded
        assert stats["indexed"] == 3
        assert stats["errors"] == 0

    def test_incremental_index_skips_unchanged(self, indexer, sample_project):
        """Second index skips unchanged files."""
        stats1 = indexer.index_directory(sample_project, "test-project")
        stats2 = indexer.index_directory(sample_project, "test-project")

        assert stats1["indexed"] == 3
        assert stats2["indexed"] == 0
        assert stats2["skipped"] == 3

    def test_incremental_index_detects_changes(self, indexer, sample_project):
        """Changed files are reindexed."""
        stats1 = indexer.index_directory(sample_project, "test-project")

        # Modify a file
        (sample_project / "main.py").write_text('"""Updated main."""\n\ndef main():\n    print("hi")\n')

        stats2 = indexer.index_directory(sample_project, "test-project")

        assert stats2["indexed"] == 1  # Only the changed file

    def test_full_reindex_clears_manifest(self, indexer, sample_project):
        """Full reindex processes all files."""
        stats1 = indexer.index_directory(sample_project, "test-project")
        stats2 = indexer.index_directory(sample_project, "test-project", full_reindex=True)

        assert stats1["indexed"] == 3
        assert stats2["indexed"] == 3

    def test_search_returns_results(self, indexer, sample_project):
        """Search returns relevant results."""
        indexer.index_directory(sample_project, "test-project")

        results = indexer.search("helper function", "test-project")

        assert len(results) > 0
        # Should find utils.py which has helper function
        file_paths = [r["metadata"]["file_path"] for r in results]
        assert any("utils" in p for p in file_paths)

    def test_search_empty_collection(self, indexer):
        """Search on non-existent project returns empty."""
        results = indexer.search("anything", "nonexistent-project")
        assert results == []

    def test_delete_project(self, indexer, sample_project):
        """Delete removes project collections."""
        indexer.index_directory(sample_project, "test-project")
        assert "test-project-code" in indexer.list_collections()

        indexer.delete_project("test-project")

        # Collections should be gone
        collections = indexer.list_collections()
        assert "test-project-code" not in collections
        assert "test-project-docs" not in collections

    def test_excludes_binary_files(self, indexer, tmp_path):
        """Binary files are skipped."""
        project = tmp_path / "project"
        project.mkdir()

        # Create a binary file with null bytes
        (project / "binary.py").write_bytes(b"# Code\x00\x01\x02")
        # Create a normal file
        (project / "normal.py").write_text("# Normal code\n")

        stats = indexer.index_directory(project, "test-project")

        assert stats["indexed"] == 1  # Only normal.py
        assert stats["skipped"] == 1  # Binary file skipped

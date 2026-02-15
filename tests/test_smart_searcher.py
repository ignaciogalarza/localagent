"""Tests for the smart_searcher subagent."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from localagent.schemas import SmartSearchResult, SearchMatch, SummarizeResult
from localagent.subagents.smart_searcher import (
    smart_search,
    _format_matches_for_summary,
    _estimate_tokens,
)


class TestEstimateTokens:
    """Test token estimation."""

    def test_estimate_tokens_short(self):
        """Short text estimation."""
        tokens = _estimate_tokens("hello world")
        assert tokens >= 2  # At least 2 tokens for 2 words

    def test_estimate_tokens_empty(self):
        """Empty string returns 0."""
        tokens = _estimate_tokens("")
        assert tokens == 0


class TestFormatMatches:
    """Test match formatting for summarization."""

    def test_format_matches_basic(self):
        """Formats matches into readable text."""
        matches = [
            {
                "content": "def helper():\n    return 42",
                "metadata": {
                    "file_path": "utils.py",
                    "start_line": 1,
                    "end_line": 2,
                },
            }
        ]

        formatted = _format_matches_for_summary(matches, "helper function")

        assert "Query: helper function" in formatted
        assert "utils.py" in formatted
        assert "def helper()" in formatted

    def test_format_matches_truncates_long_content(self):
        """Long content is truncated."""
        long_content = "x" * 2000
        matches = [
            {
                "content": long_content,
                "metadata": {"file_path": "big.py", "start_line": 1, "end_line": 100},
            }
        ]

        formatted = _format_matches_for_summary(matches, "query")

        # Should be truncated to ~1000 chars + "..."
        assert "..." in formatted
        assert len(formatted) < len(long_content) + 500


class TestSmartSearch:
    """Test smart_search function."""

    @pytest.fixture
    def mock_indexer(self):
        """Create mock indexer."""
        with patch("localagent.subagents.smart_searcher.get_indexer") as mock:
            indexer = MagicMock()
            mock.return_value = indexer
            yield indexer

    @pytest.fixture
    def mock_summarizer(self):
        """Create mock summarizer."""
        with patch("localagent.subagents.smart_searcher.summarize_content") as mock:
            mock.return_value = SummarizeResult(
                summary="Test summary of search results",
                token_count=10,
                was_compressed=True,
                model_used="test-model",
                confidence=0.9,
            )
            yield mock

    def test_smart_search_returns_result(self, mock_indexer, mock_summarizer):
        """Smart search returns SmartSearchResult."""
        mock_indexer.search.return_value = [
            {
                "content": "def test():\n    pass",
                "metadata": {
                    "file_path": "test.py",
                    "start_line": 1,
                    "end_line": 2,
                    "extension": ".py",
                },
                "distance": 0.5,
                "collection_type": "code",
            }
        ]

        result = smart_search("test function", project_name="test-project")

        assert isinstance(result, SmartSearchResult)
        assert result.query == "test function"
        assert len(result.matches) == 1
        assert result.matches[0].file_path == "test.py"

    def test_smart_search_no_matches(self, mock_indexer, mock_summarizer):
        """Smart search handles no matches."""
        mock_indexer.search.return_value = []

        result = smart_search("nonexistent query", project_name="test-project")

        assert result.total_matches == 0
        assert "No matches found" in result.summary
        assert result.confidence == 1.0  # Confident there are no matches

    def test_smart_search_with_summarization(self, mock_indexer, mock_summarizer):
        """Smart search calls summarizer when matches found."""
        mock_indexer.search.return_value = [
            {
                "content": "def helper():\n    return 42",
                "metadata": {"file_path": "utils.py", "start_line": 1, "end_line": 2, "extension": ".py"},
                "distance": 0.3,
                "collection_type": "code",
            }
        ]

        result = smart_search("helper function", summarize=True)

        mock_summarizer.assert_called_once()
        assert result.summary == "Test summary of search results"

    def test_smart_search_without_summarization(self, mock_indexer):
        """Smart search can skip summarization."""
        mock_indexer.search.return_value = [
            {
                "content": "code",
                "metadata": {"file_path": "test.py", "start_line": 1, "end_line": 1, "extension": ".py"},
                "distance": 0.5,
                "collection_type": "code",
            }
        ]

        result = smart_search("query", summarize=False)

        # Should have a basic summary without LLM
        assert "Found 1 matches" in result.summary
        assert result.confidence == 0.7

    def test_smart_search_respects_top_k(self, mock_indexer, mock_summarizer):
        """Smart search respects top_k parameter."""
        mock_indexer.search.return_value = []

        smart_search("query", top_k=10)

        mock_indexer.search.assert_called_once()
        call_kwargs = mock_indexer.search.call_args
        assert call_kwargs[1]["top_k"] == 10

    def test_smart_search_collection_type(self, mock_indexer, mock_summarizer):
        """Smart search respects collection_type."""
        mock_indexer.search.return_value = []

        smart_search("query", collection_type="docs")

        call_kwargs = mock_indexer.search.call_args
        assert call_kwargs[1]["collection_type"] == "docs"

    def test_smart_search_match_metadata(self, mock_indexer, mock_summarizer):
        """Smart search preserves match metadata."""
        mock_indexer.search.return_value = [
            {
                "content": "# README\n\nTest project",
                "metadata": {
                    "file_path": "README.md",
                    "start_line": 1,
                    "end_line": 3,
                    "extension": ".md",
                },
                "distance": 0.2,
                "collection_type": "docs",
            }
        ]

        result = smart_search("readme")

        match = result.matches[0]
        assert match.file_path == "README.md"
        assert match.distance == 0.2
        assert match.metadata["start_line"] == 1
        assert match.metadata["collection_type"] == "docs"


class TestSmartSearchIntegration:
    """Integration tests for smart search (require actual indexer)."""

    @pytest.fixture
    def indexed_project(self, tmp_path):
        """Create and index a sample project."""
        from localagent.indexer import Indexer

        project = tmp_path / "project"
        project.mkdir()

        # Create test files
        (project / "auth.py").write_text('''"""Authentication module."""

def login(username: str, password: str) -> bool:
    """Authenticate a user."""
    # Check credentials against database
    return True

def logout(session_id: str) -> None:
    """End user session."""
    pass
''')

        (project / "cache.py").write_text('''"""Caching utilities."""

def get_cached(key: str) -> str | None:
    """Retrieve cached value."""
    return None

def set_cached(key: str, value: str, ttl: int = 300) -> None:
    """Store value in cache with TTL."""
    pass
''')

        (project / "README.md").write_text('''# Test Project

This project handles user authentication and caching.

## Features
- Login/logout
- Session management
- Redis caching
''')

        # Index it
        chroma_dir = tmp_path / "chroma"
        manifest = tmp_path / "manifest.json"
        indexer = Indexer(chroma_dir=chroma_dir, manifest_path=manifest)
        indexer.index_directory(project, "test-integration")

        return project, indexer

    @pytest.mark.integration
    def test_search_finds_authentication_code(self, indexed_project, mock_summarizer):
        """Search finds authentication-related code."""
        project, indexer = indexed_project

        with patch("localagent.subagents.smart_searcher.get_indexer", return_value=indexer):
            with patch("localagent.subagents.smart_searcher.summarize_content") as mock_sum:
                mock_sum.return_value = SummarizeResult(
                    summary="Found auth code",
                    token_count=5,
                    was_compressed=True,
                    model_used="test",
                    confidence=0.9,
                )

                result = smart_search(
                    "user authentication login",
                    project_name="test-integration",
                )

        assert result.total_matches > 0
        # Should find auth.py
        file_paths = [m.file_path for m in result.matches]
        assert any("auth" in p for p in file_paths)

    @pytest.fixture
    def mock_summarizer(self):
        """Mock summarizer for integration tests."""
        return MagicMock()

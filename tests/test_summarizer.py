"""Tests for summarizer subagent."""

import pytest
from unittest.mock import patch, MagicMock

from localagent.subagents.summarizer import (
    summarize_content,
    check_ollama_health,
    _estimate_tokens,
    _truncate_to_tokens,
    _parse_llm_response,
    _chunk_content,
    SubagentUnavailableError,
)


class TestSummarizerHelpers:
    """Test helper functions."""

    def test_estimate_tokens_basic(self):
        """Verify token estimation."""
        text = "one two three four five"
        tokens = _estimate_tokens(text)
        assert 5 <= tokens <= 10

    def test_truncate_to_tokens_short_text(self):
        """Short text should not be truncated."""
        text = "Short text"
        result = _truncate_to_tokens(text, 100)
        assert result == text

    def test_truncate_to_tokens_long_text(self):
        """Long text should be truncated with ellipsis."""
        text = " ".join(["word"] * 100)
        result = _truncate_to_tokens(text, 10)
        assert result.endswith("...")
        assert len(result.split()) < 100

    def test_parse_llm_response_structured(self):
        """Parse structured LLM response."""
        response = "SUMMARY: This is the summary.\nCONFIDENCE: 0.85"
        summary, confidence = _parse_llm_response(response)
        assert summary == "This is the summary."
        assert confidence == 0.85

    def test_parse_llm_response_unstructured(self):
        """Parse unstructured LLM response."""
        response = "Just a plain response without structure."
        summary, confidence = _parse_llm_response(response)
        assert summary == response
        assert confidence == 0.8  # Default

    def test_chunk_content_small(self):
        """Small content should not be chunked."""
        content = "Small content"
        chunks = _chunk_content(content, max_chunk_tokens=1000)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_chunk_content_large(self):
        """Large content should be chunked."""
        # Create content with natural boundaries
        content = "\n\ndef func1():\n    pass\n\ndef func2():\n    pass\n" * 100
        chunks = _chunk_content(content, max_chunk_tokens=50)
        assert len(chunks) > 1


class TestSummarizer:
    """Test summarizer subagent."""

    def test_short_content_returned_verbatim(self):
        """Content under limit should not be summarized."""
        short_content = "Simple function that adds two numbers."
        result = summarize_content(content=short_content, max_tokens=200)
        assert result.summary == short_content
        assert result.was_compressed is False
        assert result.confidence == 1.0

    @patch("localagent.subagents.summarizer._call_ollama")
    def test_long_content_summarized(self, mock_ollama):
        """Long content should be summarized via Ollama."""
        mock_ollama.return_value = "SUMMARY: A distributed caching system.\nCONFIDENCE: 0.9"

        long_content = "This system implements a distributed cache. " * 100
        result = summarize_content(
            content=long_content,
            max_tokens=200,
            model="mistral:7b-instruct-q4_0",
        )

        assert result.was_compressed is True
        assert "caching" in result.summary.lower() or "cache" in result.summary.lower()
        assert result.model_used == "mistral:7b-instruct-q4_0"
        mock_ollama.assert_called_once()

    @patch("localagent.subagents.summarizer._call_ollama")
    def test_ollama_unavailable_returns_truncated(self, mock_ollama):
        """When Ollama is unavailable, return truncated content."""
        mock_ollama.side_effect = SubagentUnavailableError("Connection refused")

        long_content = "Important content " * 100
        result = summarize_content(content=long_content, max_tokens=50)

        assert result.was_compressed is True
        assert result.model_used == "truncation-fallback"
        assert result.confidence == 0.3
        assert result.token_count <= 70  # Allow some overhead

    @patch("localagent.subagents.summarizer._call_ollama")
    def test_summary_respects_token_limit(self, mock_ollama):
        """Summary should respect max_tokens limit."""
        # Return a long summary
        mock_ollama.return_value = "SUMMARY: " + "word " * 500 + "\nCONFIDENCE: 0.9"

        result = summarize_content(
            content="long content " * 100,
            max_tokens=50,
        )

        assert result.token_count <= 70  # Allow some overhead

    @patch("httpx.Client")
    def test_check_ollama_health_success(self, mock_client_class):
        """Health check returns True when Ollama responds."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        assert check_ollama_health() is True

    @patch("httpx.Client")
    def test_check_ollama_health_failure(self, mock_client_class):
        """Health check returns False when Ollama unavailable."""
        mock_client_class.return_value.__enter__.side_effect = Exception("Connection refused")

        assert check_ollama_health() is False


class TestSummarizerIntegration:
    """Integration tests requiring Ollama (marked for conditional running)."""

    @pytest.mark.integration
    def test_real_ollama_summarization(self):
        """Test actual Ollama summarization (requires running Ollama)."""
        if not check_ollama_health():
            pytest.skip("Ollama not available")

        # Content must exceed max_tokens to trigger compression
        content = """
        The LocalAgent system is a prototype for delegating tasks from a
        high-level AI planner to local subagents. It uses a HTTP broker
        running on localhost:8000 to coordinate file scanning, summarization,
        and sandboxed bash command execution. The system prioritizes token
        efficiency by using content-addressable caching and 200-token summary
        limits. The architecture consists of several components including a
        file scanner that uses glob patterns to find files and compute SHA256
        hashes, a summarizer that calls Ollama for compression, and a cache
        that stores results by content hash for deduplication. This enables
        efficient orchestration where the high-level planner can request
        summaries without loading full file contents into its context window.
        """ * 3  # Repeat to ensure content exceeds token limit

        result = summarize_content(content=content, max_tokens=100)

        # Content is long enough that it should be compressed
        assert result.was_compressed is True or result.token_count <= 100
        # Skip confidence check if Ollama fell back to truncation
        if result.model_used != "truncation-fallback":
            assert result.confidence > 0.5
        assert result.token_count <= 150

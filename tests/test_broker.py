"""Tests for HTTP broker contract compliance."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from localagent.broker import app
from localagent.schemas import TaskStatus


class TestBrokerContract:
    """Test HTTP broker enforces request/response contracts."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_valid_file_scanner_delegation(self, client, tmp_path):
        """Verify /delegate accepts valid file_scanner request."""
        request = {
            "task_id": "task-001",
            "tool_name": "file_scanner",
            "input_refs": [{"type": "glob", "value": "*.py"}],
            "max_summary_tokens": 200,
        }

        response = client.post("/delegate", json=request)

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-001"
        assert data["status"] in ["completed", "failed"]
        assert "summary" in data
        assert "result_refs" in data
        assert "confidence" in data

    @patch("localagent.broker.summarize_content")
    def test_valid_summarizer_delegation(self, mock_summarize, client):
        """Verify /delegate accepts valid summarizer request."""
        from localagent.schemas import SummarizeResult

        mock_summarize.return_value = SummarizeResult(
            summary="Test summary",
            token_count=10,
            was_compressed=True,
            model_used="test-model",
            confidence=0.9,
        )

        request = {
            "task_id": "task-002",
            "tool_name": "summarizer",
            "input_refs": [{"type": "content", "value": "Long content to summarize " * 50}],
            "max_summary_tokens": 200,
        }

        response = client.post("/delegate", json=request)

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-002"
        assert data["status"] == "completed"

    def test_invalid_tool_name_returns_422(self, client):
        """Unknown tools should be rejected."""
        request = {
            "task_id": "x",
            "tool_name": "unknown_tool",
            "input_refs": [],
            "max_summary_tokens": 200,
        }

        response = client.post("/delegate", json=request)
        assert response.status_code == 422  # Validation error

    def test_missing_required_fields_returns_422(self, client):
        """Missing required fields should fail validation."""
        request = {
            "tool_name": "file_scanner",
            # Missing task_id
        }

        response = client.post("/delegate", json=request)
        assert response.status_code == 422


class TestHealthEndpoint:
    """Test health check endpoint."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_health_endpoint_returns_status(self, client):
        """Health endpoint returns broker status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["broker"] == "healthy"
        assert "ollama" in data

    @patch("localagent.broker.check_ollama_health")
    def test_health_reports_ollama_status(self, mock_health, client):
        """Health endpoint reports Ollama status."""
        mock_health.return_value = True

        response = client.get("/health")
        data = response.json()
        assert data["ollama"] in ["healthy", "unhealthy"]


class TestFetchDetailEndpoint:
    """Test fetch_detail endpoint."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_fetch_detail_not_found(self, client):
        """Fetch detail returns 404 for missing hash."""
        request = {
            "task_id": "fetch-001",
            "hash": "sha256:" + "0" * 64,
            "format": "raw",
        }

        response = client.post("/fetch_detail", json=request)
        assert response.status_code == 404

    @patch("localagent.broker.get_cache")
    def test_fetch_detail_returns_cached_content(self, mock_get_cache, client):
        """Fetch detail returns cached content."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = {
            "summary": "Cached summary",
            "content": "Full cached content",
        }
        mock_get_cache.return_value = mock_cache

        request = {
            "task_id": "fetch-002",
            "hash": "sha256:" + "a" * 64,
            "format": "raw",
        }

        response = client.post("/fetch_detail", json=request)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "content" in data


class TestCacheIntegration:
    """Test cache integration with broker."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @patch("localagent.broker.summarize_content")
    @patch("localagent.broker.get_cache")
    def test_cache_hit_skips_summarization(self, mock_get_cache, mock_summarize, client):
        """Cache hit should return cached result without calling summarizer."""
        from localagent.cache import compute_content_hash

        content = "Test content for caching"
        content_hash = compute_content_hash(content)

        mock_cache = MagicMock()
        mock_cache.get.return_value = {
            "summary": "Cached summary",
            "confidence": 0.95,
        }
        mock_get_cache.return_value = mock_cache

        request = {
            "task_id": "cache-test-001",
            "tool_name": "summarizer",
            "input_refs": [{"type": "content", "value": content}],
            "max_summary_tokens": 200,
        }

        response = client.post("/delegate", json=request)

        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Cached summary"
        mock_summarize.assert_not_called()

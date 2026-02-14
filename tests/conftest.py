"""Pytest configuration and fixtures for LocalAgent tests."""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory for tests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def sample_python_files(tmp_workspace: Path) -> Path:
    """Create sample Python files for testing file_scanner."""
    # Create a simple Python module
    (tmp_workspace / "main.py").write_text(
        '''"""Main module."""

def main():
    """Entry point."""
    print("Hello, LocalAgent!")

if __name__ == "__main__":
    main()
'''
    )

    # Create a utils module
    utils_dir = tmp_workspace / "utils"
    utils_dir.mkdir()
    (utils_dir / "__init__.py").write_text('"""Utils package."""\n')
    (utils_dir / "helpers.py").write_text(
        '''"""Helper functions."""

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b
'''
    )

    return tmp_workspace


@pytest.fixture
def sample_large_content() -> str:
    """Generate large content for summarizer testing."""
    return "This system implements a distributed cache with Redis backend. " * 200


@pytest.fixture
def mock_ollama_response() -> dict:
    """Mock Ollama API response."""
    return {
        "model": "mistral:7b-instruct-q4_0",
        "response": "A distributed caching system using Redis for data storage.",
        "done": True,
    }


@pytest.fixture
def cache_db_path(tmp_path: Path) -> Path:
    """Create a temporary path for cache database."""
    return tmp_path / "cache.db"

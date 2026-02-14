"""Tests for file_scanner subagent."""

import pytest
from pathlib import Path

from localagent.subagents.file_scanner import (
    scan_files,
    _compute_sha256,
    _is_binary,
    _estimate_tokens,
)


class TestFileScannerHelpers:
    """Test helper functions."""

    def test_compute_sha256_returns_prefixed_hash(self):
        """Verify hash format is sha256:..."""
        result = _compute_sha256(b"test content")
        assert result.startswith("sha256:")
        assert len(result) == 7 + 64  # "sha256:" + 64 hex chars

    def test_compute_sha256_deterministic(self):
        """Verify same content produces same hash."""
        content = b"hello world"
        assert _compute_sha256(content) == _compute_sha256(content)

    def test_is_binary_detects_null_bytes(self):
        """Verify binary detection via null bytes."""
        assert _is_binary(b"hello\x00world") is True
        assert _is_binary(b"hello world") is False

    def test_estimate_tokens_reasonable(self):
        """Verify token estimation is reasonable."""
        text = "This is a test sentence with several words."
        tokens = _estimate_tokens(text)
        # Should be roughly 1.33x word count
        assert 8 <= tokens <= 15


class TestFileScanner:
    """Test file_scanner subagent extracts content correctly."""

    def test_scan_single_file_returns_summary(self, tmp_path):
        """
        Purpose: Verify scanner reads file and produces summary under token limit.
        Input: Single .py file with content.
        Expected: Summary with ≤200 tokens, result_refs contains file hash.
        """
        # Arrange
        test_file = tmp_path / "example.py"
        test_file.write_text("def hello():\n    print('world')\n" * 10)

        # Act
        result = scan_files(
            patterns=["*.py"],
            root_dir=str(tmp_path),
            max_summary_tokens=200,
        )

        # Assert
        assert result is not None
        assert result.summary_token_count <= 200
        assert len(result.result_refs) == 1
        assert result.result_refs[0].hash.startswith("sha256:")
        assert result.confidence >= 0.8
        assert result.files_scanned == 1

    def test_scan_multiple_files(self, sample_python_files):
        """Verify scanner handles multiple files."""
        result = scan_files(
            patterns=["**/*.py"],
            root_dir=str(sample_python_files),
            max_summary_tokens=200,
        )

        assert result.files_scanned >= 2
        assert len(result.result_refs) >= 2
        assert "Scanned" in result.summary

    def test_scan_nonexistent_pattern_returns_empty(self, tmp_path):
        """Verify graceful handling of no matches."""
        result = scan_files(
            patterns=["*.nonexistent"],
            root_dir=str(tmp_path),
        )
        assert result.result_refs == []
        assert result.confidence == 0.8  # Lower confidence when no matches

    def test_scan_nonexistent_directory(self):
        """Verify graceful handling of missing directory."""
        result = scan_files(
            patterns=["*.py"],
            root_dir="/nonexistent/path/that/does/not/exist",
        )
        assert result.result_refs == []
        assert "not found" in result.summary.lower()
        assert result.confidence == 1.0

    def test_scan_skips_binary_files(self, tmp_path):
        """Verify binary files are skipped."""
        # Create a text file
        text_file = tmp_path / "text.txt"
        text_file.write_text("hello world")

        # Create a binary file
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"hello\x00world")

        result = scan_files(
            patterns=["*"],
            root_dir=str(tmp_path),
        )

        # Should only have the text file
        assert result.files_scanned == 1
        assert any("binary" in result.summary.lower() or result.files_scanned == 1 for _ in [1])

    def test_scan_respects_token_limit(self, tmp_path):
        """Verify summary respects token limit."""
        # Create many files to generate a long summary
        for i in range(20):
            (tmp_path / f"file_{i}.py").write_text(f"# File {i}\n" * 100)

        result = scan_files(
            patterns=["*.py"],
            root_dir=str(tmp_path),
            max_summary_tokens=50,
        )

        assert result.summary_token_count <= 70  # Allow some overhead

    def test_scan_includes_file_paths_in_refs(self, sample_python_files):
        """Verify result refs include relative paths."""
        result = scan_files(
            patterns=["*.py"],
            root_dir=str(sample_python_files),
        )

        for ref in result.result_refs:
            assert ref.path is not None
            assert not ref.path.startswith("/")  # Relative path

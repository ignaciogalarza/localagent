"""Tests for the CLI module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from localagent.cli import main, index, search, serve, collections, delete, init


class TestCLI:
    """Test CLI commands."""

    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()

    def test_main_help(self, runner):
        """Main command shows help."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "LocalAgent" in result.output
        assert "semantic" in result.output.lower()

    def test_version(self, runner):
        """Version flag works."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestIndexCommand:
    """Test index command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @patch("localagent.indexer.get_indexer")
    def test_index_default_project(self, mock_get_indexer, runner, tmp_path):
        """Index uses directory name as default project."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {
            "indexed": 5,
            "skipped": 0,
            "errors": 0,
        }
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Create some files
            Path("test.py").write_text("# test")

            result = runner.invoke(index, ["--dir", "."])

        assert result.exit_code == 0
        assert "Indexed: 5" in result.output

    @patch("localagent.indexer.get_indexer")
    def test_index_custom_project(self, mock_get_indexer, runner, tmp_path):
        """Index accepts custom project name."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {
            "indexed": 3,
            "skipped": 1,
            "errors": 0,
        }
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(index, ["--project", "myapp", "--dir", "."])

        assert result.exit_code == 0
        mock_indexer.index_directory.assert_called_once()
        call_args = mock_indexer.index_directory.call_args
        assert call_args[1]["project"] == "myapp"

    @patch("localagent.indexer.get_indexer")
    def test_index_full_flag(self, mock_get_indexer, runner, tmp_path):
        """Index --full triggers full reindex."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {
            "indexed": 10,
            "skipped": 0,
            "errors": 0,
        }
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(index, ["--full", "--dir", "."])

        assert result.exit_code == 0
        assert "Full reindex" in result.output
        call_args = mock_indexer.index_directory.call_args
        assert call_args[1]["full_reindex"] is True


class TestSearchCommand:
    """Test search command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @patch("localagent.subagents.smart_searcher.smart_search")
    def test_search_basic(self, mock_search, runner):
        """Basic search works."""
        from localagent.schemas import SmartSearchResult, SearchMatch

        mock_search.return_value = SmartSearchResult(
            query="test query",
            matches=[
                SearchMatch(
                    file_path="test.py",
                    chunk_content="def test(): pass",
                    distance=0.3,
                    metadata={"start_line": 1, "end_line": 1},
                )
            ],
            summary="Found test function",
            summary_token_count=5,
            confidence=0.9,
            collection_searched="code",
            total_matches=1,
        )

        result = runner.invoke(search, ["test query"])

        assert result.exit_code == 0
        assert "test.py" in result.output
        assert "Found 1 matches" in result.output

    @patch("localagent.subagents.smart_searcher.smart_search")
    def test_search_raw_output(self, mock_search, runner):
        """Search --raw outputs JSON."""
        from localagent.schemas import SmartSearchResult

        mock_search.return_value = SmartSearchResult(
            query="query",
            matches=[],
            summary="No matches",
            summary_token_count=2,
            confidence=1.0,
            collection_searched="all",
            total_matches=0,
        )

        result = runner.invoke(search, ["query", "--raw"])

        assert result.exit_code == 0
        assert '"query": "query"' in result.output

    @patch("localagent.subagents.smart_searcher.smart_search")
    def test_search_no_summary_flag(self, mock_search, runner):
        """Search --no-summary skips LLM."""
        from localagent.schemas import SmartSearchResult

        mock_search.return_value = SmartSearchResult(
            query="query",
            matches=[],
            summary="No matches",
            summary_token_count=2,
            confidence=1.0,
            collection_searched="all",
            total_matches=0,
        )

        runner.invoke(search, ["query", "--no-summary"])

        mock_search.assert_called_once()
        assert mock_search.call_args[1]["summarize"] is False

    @patch("localagent.subagents.smart_searcher.smart_search")
    def test_search_top_k(self, mock_search, runner):
        """Search --top-k parameter works."""
        from localagent.schemas import SmartSearchResult

        mock_search.return_value = SmartSearchResult(
            query="query",
            matches=[],
            summary="No matches",
            summary_token_count=2,
            confidence=1.0,
            collection_searched="all",
            total_matches=0,
        )

        runner.invoke(search, ["query", "--top-k", "10"])

        mock_search.assert_called_once()
        assert mock_search.call_args[1]["top_k"] == 10


class TestServeCommand:
    """Test serve command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @patch("uvicorn.run")
    def test_serve_default_port(self, mock_uvicorn_run, runner):
        """Serve uses default port 8000."""
        runner.invoke(serve, [])

        mock_uvicorn_run.assert_called_once()
        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["port"] == 8000
        assert call_kwargs["host"] == "127.0.0.1"

    @patch("uvicorn.run")
    def test_serve_custom_port(self, mock_uvicorn_run, runner):
        """Serve accepts custom port."""
        runner.invoke(serve, ["--port", "9000"])

        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["port"] == 9000


class TestCollectionsCommand:
    """Test collections command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @patch("localagent.indexer.get_indexer")
    def test_collections_empty(self, mock_get_indexer, runner):
        """Shows message when no collections."""
        mock_indexer = MagicMock()
        mock_indexer.list_collections.return_value = []
        mock_get_indexer.return_value = mock_indexer

        result = runner.invoke(collections)

        assert result.exit_code == 0
        assert "No collections found" in result.output

    @patch("localagent.indexer.get_indexer")
    def test_collections_lists(self, mock_get_indexer, runner):
        """Lists existing collections."""
        mock_indexer = MagicMock()
        mock_indexer.list_collections.return_value = [
            "myapp-code",
            "myapp-docs",
            "other-code",
        ]
        mock_get_indexer.return_value = mock_indexer

        result = runner.invoke(collections)

        assert result.exit_code == 0
        assert "myapp-code" in result.output
        assert "myapp-docs" in result.output


class TestDeleteCommand:
    """Test delete command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @patch("localagent.indexer.get_indexer")
    def test_delete_with_confirmation(self, mock_get_indexer, runner):
        """Delete requires confirmation."""
        mock_indexer = MagicMock()
        mock_get_indexer.return_value = mock_indexer

        result = runner.invoke(delete, ["myapp", "--yes"])

        assert result.exit_code == 0
        mock_indexer.delete_project.assert_called_once_with("myapp")
        assert "Deleted" in result.output

    @patch("localagent.indexer.get_indexer")
    def test_delete_aborted(self, mock_get_indexer, runner):
        """Delete can be aborted."""
        mock_indexer = MagicMock()
        mock_get_indexer.return_value = mock_indexer

        result = runner.invoke(delete, ["myapp"], input="n\n")

        assert result.exit_code == 1
        mock_indexer.delete_project.assert_not_called()


class TestInitCommand:
    """Test init command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @patch("localagent.indexer.get_indexer")
    def test_init_creates_claude_md(self, mock_get_indexer, runner, tmp_path):
        """Init creates CLAUDE.md with instructions."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {"indexed": 0, "skipped": 0, "errors": 0}
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init, ["--project", "testproj"])

            assert result.exit_code == 0
            assert Path("CLAUDE.md").exists()

            content = Path("CLAUDE.md").read_text()
            assert "smart_search" in content
            assert "testproj" in content

    @patch("localagent.indexer.get_indexer")
    def test_init_creates_mcp_json(self, mock_get_indexer, runner, tmp_path):
        """Init creates .mcp.json with localagent config."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {"indexed": 0, "skipped": 0, "errors": 0}
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init, ["--project", "testproj"])

            assert result.exit_code == 0
            assert Path(".mcp.json").exists()

            import json
            config = json.loads(Path(".mcp.json").read_text())
            assert "localagent" in config["mcpServers"]
            assert config["mcpServers"]["localagent"]["args"] == ["mcp"]

    @patch("localagent.indexer.get_indexer")
    def test_init_indexes_project(self, mock_get_indexer, runner, tmp_path):
        """Init indexes the project by default."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {"indexed": 5, "skipped": 0, "errors": 0}
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init, ["--project", "testproj"])

            assert result.exit_code == 0
            mock_indexer.index_directory.assert_called_once()
            assert "Indexed: 5" in result.output

    @patch("localagent.indexer.get_indexer")
    def test_init_no_index_flag(self, mock_get_indexer, runner, tmp_path):
        """Init --no-index skips indexing."""
        mock_indexer = MagicMock()
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(init, ["--project", "testproj", "--no-index"])

            assert result.exit_code == 0
            mock_indexer.index_directory.assert_not_called()

    @patch("localagent.indexer.get_indexer")
    def test_init_appends_to_existing_claude_md(self, mock_get_indexer, runner, tmp_path):
        """Init appends to existing CLAUDE.md."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {"indexed": 0, "skipped": 0, "errors": 0}
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Create existing CLAUDE.md
            Path("CLAUDE.md").write_text("# Existing Project\n\nSome instructions.")

            result = runner.invoke(init, ["--project", "testproj"])

            assert result.exit_code == 0
            content = Path("CLAUDE.md").read_text()
            assert "Existing Project" in content
            assert "smart_search" in content

    @patch("localagent.indexer.get_indexer")
    def test_init_merges_mcp_json(self, mock_get_indexer, runner, tmp_path):
        """Init merges with existing .mcp.json."""
        mock_indexer = MagicMock()
        mock_indexer.index_directory.return_value = {"indexed": 0, "skipped": 0, "errors": 0}
        mock_get_indexer.return_value = mock_indexer

        with runner.isolated_filesystem(temp_dir=tmp_path):
            import json
            # Create existing .mcp.json with another server
            existing = {"mcpServers": {"other": {"command": "other-cmd"}}}
            Path(".mcp.json").write_text(json.dumps(existing))

            result = runner.invoke(init, ["--project", "testproj"])

            assert result.exit_code == 0
            config = json.loads(Path(".mcp.json").read_text())
            assert "other" in config["mcpServers"]
            assert "localagent" in config["mcpServers"]

"""Tests for CLI query modes and options."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from brainpalace_cli.cli import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


class TestCLIQueryModes:
    """Tests for query command with different modes and alpha."""

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_bm25_mode(self, mock_client_class, runner):
        """Test query command with --mode bm25."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_response = MagicMock()
        mock_response.results = []
        mock_response.query_time_ms = 10.0
        mock_response.total_results = 0
        mock_client.query.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["query", "test", "--mode", "bm25"])

        assert result.exit_code == 0
        # Verify query was called with mode='bm25'
        mock_client.query.assert_called_once()
        args, kwargs = mock_client.query.call_args
        assert kwargs["mode"] == "bm25"

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_hybrid_alpha(self, mock_client_class, runner):
        """Test query command with --mode hybrid and --alpha."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_response = MagicMock()
        mock_response.results = []
        mock_response.query_time_ms = 10.0
        mock_response.total_results = 0
        mock_client.query.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = runner.invoke(
            cli, ["query", "test", "--mode", "hybrid", "--alpha", "0.8"]
        )

        assert result.exit_code == 0
        # Verify query was called with mode='hybrid' and alpha=0.8
        mock_client.query.assert_called_once()
        args, kwargs = mock_client.query.call_args
        assert kwargs["mode"] == "hybrid"
        assert kwargs["alpha"] == 0.8

    def test_query_invalid_mode(self, runner):
        """Test query command with an invalid mode choice."""
        result = runner.invoke(cli, ["query", "test", "--mode", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value for" in result.output
        assert "'invalid' is not one of" in result.output

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_json_output_schema(self, mock_client_class, runner):
        """--json emits text/source/score/chunk_id/start_line/end_line (NOT
        content/file_path). start_line/end_line are nullable (A19, D6): only
        code chunks carry them."""
        import json

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        result_item = MagicMock()
        result_item.text = "chunk snippet"
        result_item.source = "src/foo.py"
        result_item.score = 0.42
        result_item.chunk_id = "chunk_1"
        result_item.metadata = {"start_line": 10, "end_line": 20}

        mock_response = MagicMock()
        mock_response.results = [result_item]
        mock_response.query_time_ms = 12.5
        mock_response.total_results = 1
        mock_response.index_blocked = None
        mock_response.routed_mode = None
        mock_client.query.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["query", "test", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert set(payload) >= {
            "query",
            "total_results",
            "query_time_ms",
            "results",
        }
        assert payload["results"][0] == {
            "text": "chunk snippet",
            "source": "src/foo.py",
            "score": 0.42,
            "chunk_id": "chunk_1",
            "start_line": 10,
            "end_line": 20,
        }
        # Guard the keys an AI consumer wrongly guessed (the bug under fix).
        assert "file_path" not in payload["results"][0]
        assert "content" not in payload["results"][0]

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_json_start_line_null_for_non_code_chunk(
        self, mock_client_class, runner
    ):
        """start_line/end_line are null, not absent, for a chunk with no line
        data (A19: doc/git_commit chunks and synthetic memory/reference
        results are ~29% of the corpus, not an edge case)."""
        import json

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        result_item = MagicMock()
        result_item.text = "some doc prose"
        result_item.source = "docs/GUIDE.md"
        result_item.score = 0.7
        result_item.chunk_id = "chunk_doc_1"
        result_item.metadata = {}  # no start_line/end_line, as chunking.py leaves it

        mock_response = MagicMock()
        mock_response.results = [result_item]
        mock_response.query_time_ms = 5.0
        mock_response.total_results = 1
        mock_response.index_blocked = None
        mock_response.routed_mode = None
        mock_client.query.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["query", "test", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["results"][0]["start_line"] is None
        assert payload["results"][0]["end_line"] is None

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_json_server_error_exits_nonzero(self, mock_client_class, runner):
        """--json server error -> {"error"} on stdout AND non-zero exit.

        Regression: a 500 must not be swallowed into silent empty output. The
        error payload has no "results" key, so consumers that only inspect
        "results" need the non-zero exit code to detect failure.
        """
        import json

        from brainpalace_cli.client import ServerError

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.query.side_effect = ServerError(
            "Server Error",
            status_code=500,
            detail="Query failed: top_k Input should be less than or equal to 50",
        )
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["query", "test", "--top-k", "10", "--json"])

        assert result.exit_code != 0
        payload = json.loads(result.output)
        assert "error" in payload
        assert "results" not in payload
        # Failure-time schema hint: the error payload teaches the success
        # shape, since raw CLI consumers have no session-start channel.
        assert "text/source/score/chunk_id" in payload["hint"]

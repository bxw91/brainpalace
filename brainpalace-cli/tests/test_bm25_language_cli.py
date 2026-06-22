"""Tests for BM25 language controls across CLI commands.

TDD tests for Task 16: --language / --bm25-engine on init, folders add, query,
status, and init --start lemma pre-flight.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from brainpalace_cli.cli import cli
from brainpalace_cli.commands.init import init_command  # noqa: I001

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(*, query_response=None, index_response=None) -> MagicMock:
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    if query_response is not None:
        mock_client.query.return_value = query_response
    if index_response is not None:
        mock_client.index.return_value = index_response
    return mock_client


def _default_query_response():
    resp = MagicMock()
    resp.results = []
    resp.query_time_ms = 5.0
    resp.total_results = 0
    return resp


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point get_xdg_config_dir() at an empty tmp dir."""
    fake_xdg = tmp_path / "_xdg"
    fake_xdg.mkdir()
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir", lambda: fake_xdg
    )
    return fake_xdg


# ---------------------------------------------------------------------------
# 1. init --language / --bm25-engine
# ---------------------------------------------------------------------------


class TestInitBm25Options:
    """init writes bm25: block into config.yaml."""

    def test_init_default_bm25_written(self, tmp_path, isolated_xdg, runner):
        """Bare init writes bm25.language=en, bm25.engine=stem into config.yaml."""
        result = runner.invoke(init_command, ["--path", str(tmp_path), "--no-start"])
        assert result.exit_code == 0, result.output

        config_yaml = tmp_path / ".brainpalace" / "config.yaml"
        data = yaml.safe_load(config_yaml.read_text())
        bm25 = data.get("bm25", {})
        assert bm25.get("language") == "en"
        assert bm25.get("engine") == "stem"

    def test_init_custom_language(self, tmp_path, isolated_xdg, runner):
        """--language hr is written into bm25.language."""
        result = runner.invoke(
            init_command, ["--path", str(tmp_path), "--no-start", "--language", "hr"]
        )
        assert result.exit_code == 0, result.output

        config_yaml = tmp_path / ".brainpalace" / "config.yaml"
        data = yaml.safe_load(config_yaml.read_text())
        assert data["bm25"]["language"] == "hr"
        assert data["bm25"]["engine"] == "stem"  # default unchanged

    def test_init_custom_engine(self, tmp_path, isolated_xdg, runner):
        """--bm25-engine lemma written to bm25.engine; no preflight without --start."""
        result = runner.invoke(
            init_command,
            ["--path", str(tmp_path), "--no-start", "--bm25-engine", "lemma"],
        )
        assert result.exit_code == 0, result.output

        config_yaml = tmp_path / ".brainpalace" / "config.yaml"
        data = yaml.safe_load(config_yaml.read_text())
        assert data["bm25"]["engine"] == "lemma"

    def test_init_language_and_engine_together(self, tmp_path, isolated_xdg, runner):
        """--language fr --bm25-engine stem both written."""
        result = runner.invoke(
            init_command,
            [
                "--path",
                str(tmp_path),
                "--no-start",
                "--language",
                "fr",
                "--bm25-engine",
                "stem",
            ],
        )
        assert result.exit_code == 0, result.output

        config_yaml = tmp_path / ".brainpalace" / "config.yaml"
        data = yaml.safe_load(config_yaml.read_text())
        assert data["bm25"]["language"] == "fr"
        assert data["bm25"]["engine"] == "stem"

    def test_init_invalid_engine_rejected(self, tmp_path, isolated_xdg, runner):
        """--bm25-engine bad-value is rejected by Click."""
        result = runner.invoke(
            init_command,
            ["--path", str(tmp_path), "--no-start", "--bm25-engine", "invalid"],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 2. init --start + lemma pre-flight
# ---------------------------------------------------------------------------


class TestInitLemmaPreflight:
    """engine=lemma with --start triggers simplemma importability check.

    We patch _preflight_providers (not the server module directly) since
    brainpalace_server is a separate package not installed in the CLI test env.
    """

    def _run_init_start(
        self, tmp_path, monkeypatch, *, simplemma_available: bool, engine: str = "lemma"
    ):
        monkeypatch.setattr(
            "brainpalace_cli.commands.init.get_xdg_config_dir",
            lambda: tmp_path / "xdg",
        )
        with (
            patch("brainpalace_cli.commands.init._preflight_providers"),
            patch("brainpalace_cli.commands.init._run_subcommand") as mock_run,
            patch(
                "brainpalace_cli.commands.init._check_simplemma_importable",
                return_value=simplemma_available,
            ),
        ):
            mock_run.return_value = {"step": "start", "status": "ok"}
            result = CliRunner().invoke(
                init_command,
                ["--path", str(tmp_path), "--start", "--bm25-engine", engine],
            )
        return result, mock_run

    def test_lemma_engine_start_fails_when_simplemma_missing(
        self, tmp_path, monkeypatch
    ):
        """engine=lemma with --start aborts with install hint when simplemma absent."""
        result, mock_run = self._run_init_start(
            tmp_path, monkeypatch, simplemma_available=False
        )
        assert result.exit_code != 0
        assert "simplemma" in result.output.lower()
        assert "pip install" in result.output
        mock_run.assert_not_called()

    def test_lemma_engine_start_succeeds_when_simplemma_present(
        self, tmp_path, monkeypatch
    ):
        """engine=lemma with --start proceeds when simplemma is importable."""
        result, mock_run = self._run_init_start(
            tmp_path, monkeypatch, simplemma_available=True
        )
        assert result.exit_code == 0, result.output
        mock_run.assert_called()

    def test_stem_engine_start_skips_simplemma_check(self, tmp_path, monkeypatch):
        """engine=stem never calls _check_simplemma_importable."""
        monkeypatch.setattr(
            "brainpalace_cli.commands.init.get_xdg_config_dir",
            lambda: tmp_path / "xdg",
        )
        with (
            patch("brainpalace_cli.commands.init._preflight_providers"),
            patch("brainpalace_cli.commands.init._run_subcommand") as mock_run,
            patch(
                "brainpalace_cli.commands.init._check_simplemma_importable",
                side_effect=AssertionError("should not be called"),
            ),
        ):
            mock_run.return_value = {"step": "start", "status": "ok"}
            result = CliRunner().invoke(
                init_command,
                ["--path", str(tmp_path), "--start", "--bm25-engine", "stem"],
            )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 3. folders add --language
# ---------------------------------------------------------------------------


class TestFoldersAddLanguage:
    """folders add --language persists bm25.language to project config."""

    @patch("brainpalace_cli.commands.folders.DocServeClient")
    @patch("brainpalace_cli.commands.folders.get_state_dir")
    def test_folders_add_language_writes_config(
        self, mock_get_state_dir, mock_client_class, runner, tmp_path
    ):
        """--language hr is written to bm25.language in project config.yaml."""
        mock_get_state_dir.return_value = tmp_path
        mock_client = _make_mock_client(
            index_response=MagicMock(job_id="job-1", status="queued", message=None)
        )
        mock_client_class.return_value = mock_client

        with runner.isolated_filesystem():
            import os

            os.makedirs("testdir", exist_ok=True)
            result = runner.invoke(
                cli, ["folders", "add", "testdir", "--language", "hr"]
            )

        assert result.exit_code == 0, result.output
        # bm25.language must be persisted to the project config
        config_yaml = tmp_path / "config.yaml"
        assert config_yaml.exists(), "config.yaml was not written"
        data = yaml.safe_load(config_yaml.read_text())
        assert data.get("bm25", {}).get("language") == "hr"
        # text_language must NOT be forwarded to the index() call
        call_kwargs = mock_client.index.call_args[1]
        assert "text_language" not in call_kwargs

    @patch("brainpalace_cli.commands.folders.DocServeClient")
    @patch("brainpalace_cli.commands.folders.get_state_dir")
    def test_folders_add_no_language_skips_config_write(
        self, mock_get_state_dir, mock_client_class, runner, tmp_path
    ):
        """Without --language, config.yaml not written; index() omits text_language."""
        mock_get_state_dir.return_value = tmp_path
        mock_client = _make_mock_client(
            index_response=MagicMock(job_id="job-2", status="queued", message=None)
        )
        mock_client_class.return_value = mock_client

        with runner.isolated_filesystem():
            import os

            os.makedirs("testdir2", exist_ok=True)
            result = runner.invoke(cli, ["folders", "add", "testdir2"])

        assert result.exit_code == 0, result.output
        # get_state_dir should not have been called (no --language supplied)
        mock_get_state_dir.assert_not_called()
        call_kwargs = mock_client.index.call_args[1]
        assert "text_language" not in call_kwargs

    @patch("brainpalace_cli.commands.folders.DocServeClient")
    def test_folders_add_language_help_shown(self, mock_client_class, runner):
        """--language appears in folders add --help."""
        result = runner.invoke(cli, ["folders", "add", "--help"])
        assert "--language" in result.output


# ---------------------------------------------------------------------------
# 4. query --language
# ---------------------------------------------------------------------------


class TestQueryLanguage:
    """query --language sends language in the request payload."""

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_language_forwarded(self, mock_client_class, runner):
        """--language hr maps to language= in the HTTP payload."""
        mock_client = _make_mock_client(query_response=_default_query_response())
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["query", "test query", "--language", "hr"])

        assert result.exit_code == 0, result.output
        call_kwargs = mock_client.query.call_args[1]
        assert call_kwargs.get("language") == "hr"

    @patch("brainpalace_cli.commands.query.DocServeClient")
    def test_query_no_language_not_sent(self, mock_client_class, runner):
        """Without --language, language is None (server picks project default)."""
        mock_client = _make_mock_client(query_response=_default_query_response())
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["query", "test query"])

        assert result.exit_code == 0, result.output
        call_kwargs = mock_client.query.call_args[1]
        assert call_kwargs.get("language") is None

    def test_query_language_in_help(self, runner):
        """--language appears in query --help."""
        result = runner.invoke(cli, ["query", "--help"])
        assert "--language" in result.output


# ---------------------------------------------------------------------------
# 5. status shows BM25 language/engine from config
# ---------------------------------------------------------------------------


class TestStatusBm25:
    """status shows BM25 language/engine read from local config.yaml."""

    @patch("brainpalace_cli.commands.status.DocServeClient")
    @patch("brainpalace_cli.commands.status._load_bm25_config_for_status")
    def test_status_shows_bm25_language_engine(
        self, mock_bm25_cfg, mock_client_class, runner, tmp_path
    ):
        """status output includes BM25 language and engine from config."""
        mock_bm25_cfg.return_value = {"language": "hr", "engine": "lemma"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.health.return_value = MagicMock(
            status="healthy", message=None, version="1.0.0"
        )
        mock_client.status.return_value = MagicMock(
            total_documents=0,
            total_chunks=0,
            indexing_in_progress=False,
            current_job_id=None,
            progress_percent=0.0,
            last_indexed_at=None,
            indexed_folders=[],
            file_watcher=None,
            embedding_cache=None,
            graph_index=None,
            features={},
            index_warnings=[],
        )
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0, result.output
        assert "hr" in result.output
        assert "lemma" in result.output

    @patch("brainpalace_cli.commands.status.DocServeClient")
    @patch("brainpalace_cli.commands.status._load_bm25_config_for_status")
    def test_status_json_includes_bm25(self, mock_bm25_cfg, mock_client_class, runner):
        """status --json includes bm25 config block."""
        mock_bm25_cfg.return_value = {"language": "de", "engine": "stem"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.health.return_value = MagicMock(
            status="healthy", message=None, version="1.0.0"
        )
        mock_client.status.return_value = MagicMock(
            total_documents=0,
            total_chunks=0,
            indexing_in_progress=False,
            current_job_id=None,
            progress_percent=0.0,
            last_indexed_at=None,
            indexed_folders=[],
            file_watcher=None,
            embedding_cache=None,
            graph_index=None,
            features={},
            index_warnings=[],
        )
        mock_client_class.return_value = mock_client

        result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data.get("bm25", {}).get("language") == "de"
        assert data.get("bm25", {}).get("engine") == "stem"

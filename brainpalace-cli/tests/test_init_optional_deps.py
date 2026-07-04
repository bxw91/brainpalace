"""Tests for _reconcile_optional_deps and typed-field write coverage."""

from unittest.mock import patch

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import _reconcile_optional_deps, init_command


def test_enabling_reranker_installs_extra():
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        _reconcile_optional_deps({"reranker.enabled": True})
        ensure.assert_called_once_with("reranker-local", assume_yes=True)


def test_lemma_engine_installs_extra():
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        _reconcile_optional_deps({"bm25.engine": "lemma"})
        ensure.assert_called_once_with("lemma-hr", assume_yes=True)


def test_no_relevant_edit_installs_nothing():
    with patch("brainpalace_cli.optional_deps.ensure_extra") as ensure:
        _reconcile_optional_deps({"embedding.provider": "ollama"})
        ensure.assert_not_called()


def test_int_field_edit_writes_int(monkeypatch, tmp_path):
    # An int field edited via the editor must be stored as an int, not a string.
    monkeypatch.setattr(
        "brainpalace_cli.xdg_paths.get_xdg_config_dir", lambda: tmp_path
    )
    monkeypatch.setattr("brainpalace_cli.commands.init._stdin_is_tty", lambda: True)
    # Drill Query Log (division 17), keep enabled (Y), set retention_days=30 (not the
    # default 7 so the edit is recorded), then c to continue, then n to skip dashboard.
    # Grid: ... 15=Server, 16=Server Mode → Query Log is division 17.
    result = CliRunner().invoke(init_command, ["--global"], input="17\nY\n30\nc\nn\n")
    assert result.exit_code == 0, result.output
    written = None
    cfg = tmp_path / "config.yaml"
    assert cfg.exists(), "Editing retention_days must write the file"
    written = yaml.safe_load(cfg.read_text())
    assert "query_log" in written
    assert isinstance(written["query_log"]["retention_days"], int), (
        f"Expected int, got {type(written['query_log']['retention_days'])}: "
        f"{written['query_log']['retention_days']!r}"
    )

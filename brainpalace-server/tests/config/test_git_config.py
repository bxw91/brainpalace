"""Tests for ``git_indexing:`` config parsing."""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.config.git_config import load_git_indexing_config


def test_path_filter_parsed(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "git_indexing:\n  enabled: true\n  path_filter:\n    - services/api\n"
    )
    cfg = load_git_indexing_config(cfg_file)
    assert cfg.path_filter == ["services/api"]


def test_path_filter_defaults_empty(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("git_indexing:\n  enabled: true\n")
    assert load_git_indexing_config(cfg_file).path_filter == []

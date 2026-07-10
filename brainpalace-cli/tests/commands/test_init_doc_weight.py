from pathlib import Path

import yaml

from brainpalace_cli.commands.init import _write_ranking_config


def test_write_ranking_config_sets_doc_weight(tmp_path: Path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    _write_ranking_config(state, 0.3)
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["ranking"]["doc_weight"] == 0.3


def test_write_ranking_config_preserves_other_sections(tmp_path: Path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(yaml.safe_dump({"reranker": {"enabled": True}}))
    _write_ranking_config(state, 0.0)
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["reranker"]["enabled"] is True
    assert data["ranking"]["doc_weight"] == 0.0

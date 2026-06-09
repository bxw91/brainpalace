"""ConfigService.unset(): remove project keys so they inherit global/code."""

from __future__ import annotations

import yaml

from brainpalace_dashboard.services.config_svc import ConfigService


def _project(tmp_path) -> object:
    state = tmp_path / "proj" / ".brainpalace"
    state.mkdir(parents=True)
    return state


def _write_global(tmp_path, monkeypatch, text: str) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    d = tmp_path / "cfg" / "brainpalace"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(text)


def test_unset_removes_key_and_reports_global_fallback(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text(
        "bm25:\n  language: hr\n  engine: stem\ngraphrag:\n  enabled: true\n"
    )
    _write_global(tmp_path, monkeypatch, "bm25:\n  language: de\n")

    result = ConfigService().unset(state, ["bm25.language"])
    assert result["removed"] == ["bm25.language"]
    assert result["effective"]["bm25.language"] == {"value": "de", "source": "global"}

    data = yaml.safe_load((state / "config.yaml").read_text())
    assert "language" not in data["bm25"]  # removed
    assert data["bm25"]["engine"] == "stem"  # sibling preserved
    assert data["graphrag"]["enabled"] is True  # other blocks preserved


def test_unset_prunes_emptied_parent_and_falls_to_code_default(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("bm25:\n  language: hr\n")
    _write_global(tmp_path, monkeypatch, "")

    result = ConfigService().unset(state, ["bm25.language"])
    assert result["removed"] == ["bm25.language"]
    # No global → falls back to the code default for bm25.language ("en").
    assert result["effective"]["bm25.language"] == {"value": "en", "source": "default"}
    data = yaml.safe_load((state / "config.yaml").read_text()) or {}
    assert "bm25" not in data  # emptied parent pruned


def test_unset_missing_key_is_noop(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("bm25:\n  engine: stem\n")
    _write_global(tmp_path, monkeypatch, "")

    result = ConfigService().unset(state, ["bm25.language"])
    assert result["removed"] == []
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data == {"bm25": {"engine": "stem"}}

"""ConfigService.effective(): per-key value + provenance across the config layers.

Resolution precedence is project > global > code default. Powers the dashboard's
"inherited from global / default" hints and empty-when-unset behavior.
"""

from __future__ import annotations

import yaml

import brainpalace_dashboard.services.config_svc as mod
from brainpalace_dashboard.services.config_svc import MASK, ConfigService


def _project(tmp_path) -> object:
    state = tmp_path / "proj" / ".brainpalace"
    state.mkdir(parents=True)
    return state


def _write_global(tmp_path, monkeypatch, text: str) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    d = tmp_path / "cfg" / "brainpalace"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(text)


def test_project_value_wins(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("graphrag:\n  enabled: false\n")
    _write_global(tmp_path, monkeypatch, "graphrag:\n  enabled: true\n")

    eff = ConfigService().effective(state)
    entry = eff["graphrag.enabled"]
    assert entry["value"] is False
    assert entry["source"] == "project"
    # A project override carries what it WOULD inherit if unset (here: global).
    assert entry["inherited"] == {"value": True, "source": "global"}


def test_global_fallback_when_project_absent(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    _write_global(tmp_path, monkeypatch, "summarization:\n  provider: gemini\n")

    eff = ConfigService().effective(state)
    assert eff["summarization.provider"]["value"] == "gemini"
    assert eff["summarization.provider"]["source"] == "global"
    # Not project-sourced → no inherited fallback attached.
    assert eff["summarization.provider"]["inherited"] is None
    assert eff["embedding.provider"]["value"] == "openai"
    assert eff["embedding.provider"]["source"] == "project"


def test_project_override_inherited_falls_to_code_default(tmp_path, monkeypatch):
    state = _project(tmp_path)
    # reranker.enabled set at project (true), absent from global → inherited =
    # the code default (false).
    (state / "config.yaml").write_text("reranker:\n  enabled: true\n")
    _write_global(tmp_path, monkeypatch, "")

    entry = ConfigService().effective(state)["reranker.enabled"]
    assert entry["source"] == "project"
    assert entry["inherited"] == {"value": False, "source": "default"}


def test_default_fallback_when_unset_everywhere(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    _write_global(tmp_path, monkeypatch, "")

    eff = ConfigService().effective(state)
    # reranker.enabled defaults False in ui_schema.DEFAULTS
    assert eff["reranker.enabled"] == {
        "value": False,
        "source": "default",
        "inherited": None,
    }


def test_secret_is_masked(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  api_key: sk-REALSECRET\n"
    )
    _write_global(tmp_path, monkeypatch, "")

    eff = ConfigService().effective(state)
    assert eff["embedding.api_key"]["value"] == MASK
    assert eff["embedding.api_key"]["source"] == "project"


def test_absent_key_is_omitted(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    _write_global(tmp_path, monkeypatch, "")

    eff = ConfigService().effective(state)
    # A made-up key set nowhere (and not in DEFAULTS) must not appear.
    assert "embedding.nonsense_key" not in eff


def test_effective_global_resolves_file_over_default(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "get_xdg_config_dir", lambda: tmp_path)
    # graphrag.enabled defaults True in code; set it false in the global file.
    (tmp_path / "config.yaml").write_text("graphrag:\n  enabled: false\n")

    svc = ConfigService()
    eff = svc.effective_global()

    # A key set in the global file -> source "global", inherited = code default.
    assert eff["graphrag.enabled"]["value"] is False
    assert eff["graphrag.enabled"]["source"] == "global"
    assert eff["graphrag.enabled"]["inherited"] == {
        "value": mod.DEFAULTS["graphrag.enabled"],
        "source": "default",
    }
    # A key absent from the file -> source "default", no inherited.
    some_default = next(k for k in mod.DEFAULTS if k != "graphrag.enabled")
    assert eff[some_default]["source"] == "default"
    assert eff[some_default]["inherited"] is None


def test_unset_global_removes_key_and_reports_default(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "get_xdg_config_dir", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text("graphrag:\n  enabled: false\n")

    svc = ConfigService()
    res = svc.unset_global(["graphrag.enabled"])

    assert res["removed"] == ["graphrag.enabled"]
    assert res["effective"]["graphrag.enabled"] == {
        "value": mod.DEFAULTS["graphrag.enabled"],
        "source": "default",
    }
    # File no longer carries the key (emptied parent pruned).
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text()) or {}
    assert "graphrag" not in on_disk

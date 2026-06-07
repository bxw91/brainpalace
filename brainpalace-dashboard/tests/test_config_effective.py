"""ConfigService.effective(): per-key value + provenance across the config layers.

Resolution precedence is project > global > code default. Powers the dashboard's
"inherited from global / default" hints and empty-when-unset behavior.
"""

from __future__ import annotations

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
    assert eff["graphrag.enabled"] == {"value": False, "source": "project"}


def test_global_fallback_when_project_absent(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    _write_global(tmp_path, monkeypatch, "summarization:\n  provider: gemini\n")

    eff = ConfigService().effective(state)
    assert eff["summarization.provider"] == {"value": "gemini", "source": "global"}
    assert eff["embedding.provider"] == {"value": "openai", "source": "project"}


def test_default_fallback_when_unset_everywhere(tmp_path, monkeypatch):
    state = _project(tmp_path)
    (state / "config.yaml").write_text("embedding:\n  provider: openai\n")
    _write_global(tmp_path, monkeypatch, "")

    eff = ConfigService().effective(state)
    # reranker.enabled defaults True in ui_schema.DEFAULTS
    assert eff["reranker.enabled"] == {"value": True, "source": "default"}


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

"""Tests for layer-aware resolve_value and state-dir-honoring review_config."""

from brainpalace_cli import config_fields as cf
from brainpalace_cli import config_review as cr


def test_resolve_value_global_reads_global_file(tmp_path, monkeypatch):
    gcfg = tmp_path / "config.yaml"
    gcfg.write_text("embedding:\n  provider: cohere\n")
    monkeypatch.setattr(cf, "load_merged_config_dict", lambda *a, **k: {})
    monkeypatch.setattr(
        "brainpalace_cli.config_resolve.global_config_path", lambda: gcfg
    )
    assert cf.resolve_value("embedding.provider", layer="global") == (
        "cohere",
        "global",
    )
    assert cf.resolve_value("reranker.enabled", layer="global") == (False, "default")


def test_review_config_project_layer_reads_state_dir_not_cwd(tmp_path, monkeypatch):
    # The project config lives at state_dir; CWD has a DIFFERENT value. The screen
    # must show the state_dir value (finding #1).
    state = tmp_path / "proj" / ".brainpalace"
    state.mkdir(parents=True)
    (state / "config.yaml").write_text("embedding:\n  provider: ollama\n")
    captured = {}
    real = cf.resolve_value

    def _spy(dp, merged=None, *, layer="project"):
        captured.setdefault("merged", merged)
        return real(dp, merged, layer=layer)

    monkeypatch.setattr(cr.cf, "resolve_value", _spy)
    monkeypatch.setattr("click.prompt", lambda *a, **k: "c")  # Continue immediately
    cr.review_config(state, on_consent=lambda s: None, layer="project")
    assert captured["merged"].get("embedding", {}).get("provider") == "ollama"

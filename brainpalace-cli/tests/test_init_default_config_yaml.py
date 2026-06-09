"""Tests for write_default_provider_config (Phase L + Phase L1 follow-up)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from brainpalace_cli.commands.init import (
    _preview_embedding,
    build_default_provider_config,
    write_default_provider_config,
)

# Every provider API-key env var init inspects when choosing defaults (Bug 0).
_ALL_PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "COHERE_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
)


@pytest.fixture
def no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all provider API keys so default selection is deterministic."""
    for key in _ALL_PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point get_xdg_config_dir() at an empty tmp dir so tests don't see
    the developer's real ~/.config/brainpalace/config.yaml."""
    fake_xdg = tmp_path / "_xdg"
    fake_xdg.mkdir()
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir", lambda: fake_xdg
    )
    return fake_xdg


def test_writes_default_config_when_absent(tmp_path: Path, isolated_xdg: Path) -> None:
    """No config.yaml, no XDG global → hardcoded default written."""
    written = write_default_provider_config(tmp_path)
    assert written is True

    config_path = tmp_path / "config.yaml"
    assert config_path.exists()

    data = yaml.safe_load(config_path.read_text())
    assert data["graphrag"]["enabled"] is True
    assert data["graphrag"]["use_code_metadata"] is True
    assert data["graphrag"]["store_type"] == "sqlite"
    # docs not opt-in by default (no LLM cost)
    assert "doc_extractor" not in data["graphrag"]


def test_idempotent_when_present(tmp_path: Path, isolated_xdg: Path) -> None:
    """Existing config.yaml → no overwrite without force."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("existing: true\n")

    written = write_default_provider_config(tmp_path)
    assert written is False
    assert config_path.read_text() == "existing: true\n"


def test_force_overwrites(tmp_path: Path, isolated_xdg: Path) -> None:
    """force=True → existing config.yaml replaced with defaults."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("old: true\n")

    written = write_default_provider_config(tmp_path, force=True)
    assert written is True

    data = yaml.safe_load(config_path.read_text())
    assert "graphrag" in data
    assert "old" not in data


def test_defaults_match_builder(tmp_path: Path, isolated_xdg: Path) -> None:
    """Written config matches build_default_provider_config (no silent drift)."""
    write_default_provider_config(tmp_path)
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data == build_default_provider_config()


def test_no_keys_falls_back_to_openai_anthropic(
    no_provider_keys: None,
) -> None:
    """No provider keys → fallback (openai embed + anthropic summarize)."""
    config = build_default_provider_config()
    assert config["embedding"]["provider"] == "openai"
    assert config["summarization"]["provider"] == "anthropic"


def test_openai_only_env_defaults_summarizer_to_openai(
    no_provider_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug 0: OPENAI_API_KEY set, ANTHROPIC absent → summarizer = openai.

    Zero-edit happy path: an openai-only user must NOT be forced to set an
    Anthropic key or edit config.yaml.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = build_default_provider_config()
    assert config["embedding"]["provider"] == "openai"
    assert config["summarization"]["provider"] == "openai"


def test_anthropic_preferred_when_present(
    no_provider_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both keys present → anthropic stays the summarization default."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    config = build_default_provider_config()
    assert config["summarization"]["provider"] == "anthropic"


def test_gemini_only_env_defaults_summarizer_to_gemini(
    no_provider_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini-only env → summarizer = gemini; embedding falls back to openai."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    config = build_default_provider_config()
    assert config["summarization"]["provider"] == "gemini"
    assert config["embedding"]["provider"] == "openai"  # no embed gemini option


def test_cohere_env_picks_cohere_embedding(
    no_provider_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """COHERE key (no OPENAI) → embedding = cohere."""
    monkeypatch.setenv("COHERE_API_KEY", "co-test")
    config = build_default_provider_config()
    assert config["embedding"]["provider"] == "cohere"


def test_inherits_xdg_global_when_present(tmp_path: Path, isolated_xdg: Path) -> None:
    """User has ~/.config/brainpalace/config.yaml → init does NOT copy it.

    Under layered resolution (code < global < project) the project INHERITS the
    global, so the project config is sparse — it must NOT duplicate the global's
    provider blocks. With no explicit per-project flags, the file is empty.
    """
    xdg_config = isolated_xdg / "config.yaml"
    user_config = {
        "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
        "summarization": {"provider": "openai", "model": "gpt-4o-mini"},
        "graphrag": {"enabled": True, "use_code_metadata": True},
    }
    xdg_config.write_text(yaml.safe_dump(user_config))

    written = write_default_provider_config(tmp_path)
    assert written is True

    data = yaml.safe_load((tmp_path / "config.yaml").read_text()) or {}
    # Inherited, not copied: no duplicated provider blocks in the project file.
    assert "summarization" not in data
    assert "embedding" not in data


def test_inherits_xdg_global_writes_only_explicit_divergences(
    tmp_path: Path, isolated_xdg: Path
) -> None:
    """With a global present, only explicit per-project flags are written."""
    (isolated_xdg / "config.yaml").write_text(
        yaml.safe_dump({"embedding": {"provider": "openai"}})
    )
    written = write_default_provider_config(tmp_path, bm25_language="hr")
    assert written is True
    data = yaml.safe_load((tmp_path / "config.yaml").read_text()) or {}
    assert data == {"bm25": {"language": "hr"}}  # only the divergence


def test_preview_embedding_prefers_project_config(tmp_path, monkeypatch):
    # An existing project config wins over env/XDG.
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        "embedding:\n  provider: cohere\n  model: embed-english-v3.0\n"
    )
    for key in _ALL_PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")  # would lose to the project config
    assert _preview_embedding(tmp_path) == ("cohere", "embed-english-v3.0")


def test_preview_embedding_falls_back_to_env_default(
    tmp_path, monkeypatch, isolated_xdg
):
    # No project/XDG config (isolated_xdg is empty) → env-detected default.
    for key in _ALL_PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert _preview_embedding(tmp_path) == ("openai", "text-embedding-3-large")

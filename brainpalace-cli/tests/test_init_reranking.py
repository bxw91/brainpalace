"""`brainpalace init` writes reranker.enabled (ON by default; --no-reranking off)."""

import yaml

from brainpalace_cli.commands.init import (
    build_default_provider_config,
    write_default_provider_config,
)


def test_default_provider_config_enables_reranking() -> None:
    cfg = build_default_provider_config()
    assert cfg["reranker"] == {"enabled": True}


def test_default_provider_config_can_disable_reranking() -> None:
    cfg = build_default_provider_config(reranking=False)
    assert cfg["reranker"] == {"enabled": False}


def test_write_default_provider_config_writes_reranker(tmp_path, monkeypatch) -> None:
    # No XDG global config -> the env-default provider block is written.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    state = tmp_path / ".brainpalace"
    written = write_default_provider_config(state, reranking=True)
    assert written
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["reranker"]["enabled"] is True


def test_write_default_provider_config_no_reranking(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    state = tmp_path / ".brainpalace"
    write_default_provider_config(state, reranking=False)
    data = yaml.safe_load((state / "config.yaml").read_text())
    assert data["reranker"]["enabled"] is False

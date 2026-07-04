"""LSP server registry + per-language gating (Phase 150 / Plan 2)."""

from __future__ import annotations

import pytest

from brainpalace_server.config import settings
from brainpalace_server.lsp import servers


def test_language_for_extension() -> None:
    assert servers.language_for_path("a/b.py") == "python"
    assert servers.language_for_path("a/b.ts") == "typescript"
    assert servers.language_for_path("a/b.go") == "go"
    assert servers.language_for_path("a/b.md") is None


def test_env_override_parses_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python, go")
    assert servers.enabled_languages() == {"python", "go"}


def test_config_off_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")
    from brainpalace_server.config.graph_indexing_config import (
        GraphIndexingConfig,
        GraphLspConfig,
    )

    monkeypatch.setattr(
        servers,
        "load_graph_indexing_config",
        lambda: GraphIndexingConfig(lsp=GraphLspConfig(mode="off")),
    )
    assert servers.enabled_languages() == set()


def test_config_on_forces_toggled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")
    from brainpalace_server.config.graph_indexing_config import (
        GraphIndexingConfig,
        GraphLspConfig,
    )

    monkeypatch.setattr(
        servers,
        "load_graph_indexing_config",
        lambda: GraphIndexingConfig(
            lsp=GraphLspConfig(mode="on", python=True, typescript=False)
        ),
    )
    # `on` ignores detection
    monkeypatch.setattr(servers, "detect_servers", lambda: set())
    assert servers.enabled_languages() == {"python"}


def test_config_auto_intersects_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")
    from brainpalace_server.config.graph_indexing_config import (
        GraphIndexingConfig,
        GraphLspConfig,
    )

    monkeypatch.setattr(
        servers,
        "load_graph_indexing_config",
        lambda: GraphIndexingConfig(
            lsp=GraphLspConfig(mode="auto", python=True, typescript=True)
        ),
    )
    monkeypatch.setattr(servers, "detect_servers", lambda: {"python"})
    assert servers.enabled_languages() == {"python"}


def test_auto_with_no_binaries_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")
    monkeypatch.setattr(servers, "detect_servers", lambda: set())
    # default config is mode=auto → nothing detected → empty
    assert servers.enabled_languages() == set()


def test_detect_servers_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        servers.shutil,
        "which",
        lambda name: "/usr/bin/x" if name == "pyright-langserver" else None,
    )
    assert servers.detect_servers() == {"python"}


def test_lsp_state_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")
    monkeypatch.setattr(servers, "detect_servers", lambda: {"python"})
    st = servers.lsp_state()
    assert st["mode"] == "auto"
    assert st["active"] == ["python"]
    assert st["detected"] == ["python"]
    assert st["via_env"] is False


def test_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python")
    assert servers.is_language_enabled("python") is True
    assert servers.is_language_enabled("go") is False


def test_server_command_known_language() -> None:
    cmd = servers.server_command("python")
    assert cmd is not None
    assert "pyright-langserver" in cmd[0] or "pyright" in " ".join(cmd)


def test_server_command_unknown_language() -> None:
    assert servers.server_command("cobol") is None


def test_configured_languages_lists_toggled_regardless_of_detection(monkeypatch):
    from brainpalace_server.lsp import servers

    class _Lsp:
        mode = "auto"
        python = True
        typescript = False

    class _Cfg:
        lsp = _Lsp()

    monkeypatch.setattr(servers, "load_graph_indexing_config", lambda: _Cfg())
    monkeypatch.setattr(servers, "_env_languages", lambda: set())
    # No servers on PATH at all:
    monkeypatch.setattr(servers, "detect_servers", lambda: set())

    assert servers.configured_languages() == {"python"}
    # enabled (auto) is gated by detection, configured is not:
    assert servers.enabled_languages() == set()
    assert servers.lsp_state()["configured"] == ["python"]


def test_configured_languages_off_is_empty(monkeypatch):
    from brainpalace_server.lsp import servers

    class _Lsp:
        mode = "off"
        python = True
        typescript = True

    class _Cfg:
        lsp = _Lsp()

    monkeypatch.setattr(servers, "load_graph_indexing_config", lambda: _Cfg())
    monkeypatch.setattr(servers, "_env_languages", lambda: set())
    assert servers.configured_languages() == set()


def test_detect_binaries_public_accessor():
    from brainpalace_server.lsp import servers

    assert servers.detect_binaries("python") == ("pyright-langserver", "pyright")
    assert servers.detect_binaries("nonsense") == ()

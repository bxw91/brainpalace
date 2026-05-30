"""LSP server registry + per-language gating (Phase 150)."""

from __future__ import annotations

import pytest

from brainpalace_server.config import settings
from brainpalace_server.lsp import servers


def test_language_for_extension() -> None:
    assert servers.language_for_path("a/b.py") == "python"
    assert servers.language_for_path("a/b.ts") == "typescript"
    assert servers.language_for_path("a/b.go") == "go"
    assert servers.language_for_path("a/b.md") is None


def test_enabled_languages_parses_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "python, go")
    assert servers.enabled_languages() == {"python", "go"}


def test_enabled_languages_empty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BRAINPALACE_LSP_LANGUAGES", "")
    assert servers.enabled_languages() == set()


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

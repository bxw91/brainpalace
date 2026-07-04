"""Per-language LSP server registry + gating (Phase 150, Plan 2).

Maps file extensions → language ids and language ids → launch commands, and
resolves which languages are LSP-enabled. Resolution precedence:

1. legacy env ``BRAINPALACE_LSP_LANGUAGES`` (non-empty) — explicit override,
2. otherwise the ``graph_indexing.lsp`` config: ``off`` → none, ``on`` →
   on-toggled languages, ``auto`` → on-toggled ∩ binaries detected on PATH.

A missing server binary is handled by the caller (fail-soft).
"""

from __future__ import annotations

import os
import shutil

from brainpalace_server.config.graph_indexing_config import (
    load_graph_indexing_config,
)
from brainpalace_server.config.settings import get_settings

# file extension -> LSP language id
_EXT_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",  # ts server handles js
    ".jsx": "typescript",
    ".go": "go",
}

# language id -> launch command (stdio). Binaries are user-installed; discovery
# + fail-soft happens at spawn time.
_SERVER_COMMANDS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "go": ["gopls"],
}

# language id -> candidate binary names probed for auto-detection (PATH/venv).
# Order is informational only; any hit enables the language.
_DETECT_BINARIES: dict[str, tuple[str, ...]] = {
    "python": ("pyright-langserver", "pyright"),
    "typescript": ("typescript-language-server", "tsserver"),
}

# languages the config model exposes a per-language toggle for (auto/on apply
# only to these; `go` etc. remain env-override-only).
_CONFIG_LANGUAGES: tuple[str, ...] = ("python", "typescript")


def language_for_path(path: str) -> str | None:
    """Return the LSP language id for a file path, or None if unsupported."""
    _, ext = os.path.splitext(path)
    return _EXT_LANGUAGE.get(ext.lower())


def server_command(language: str) -> list[str] | None:
    """Launch command for a language's LSP server, or None if unknown."""
    cmd = _SERVER_COMMANDS.get(language)
    return list(cmd) if cmd else None


def detect_servers() -> set[str]:
    """Languages whose server binary is found on PATH (``shutil.which``)."""
    found: set[str] = set()
    for language, candidates in _DETECT_BINARIES.items():
        if any(shutil.which(name) for name in candidates):
            found.add(language)
    return found


def _env_languages() -> set[str]:
    raw = get_settings().BRAINPALACE_LSP_LANGUAGES or ""
    if not isinstance(raw, str):
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def detect_binaries(lang: str) -> tuple[str, ...]:
    """Public accessor: candidate server binary names probed for a language."""
    return _DETECT_BINARIES.get(lang, ())


def configured_languages() -> set[str]:
    """Languages toggled on in graph_indexing.lsp, regardless of whether a
    server binary is installed. env override still wins for back-compat."""
    env = _env_languages()
    if env:
        return env
    lsp = load_graph_indexing_config().lsp
    if lsp.mode == "off":
        return set()
    return {lang for lang in _CONFIG_LANGUAGES if getattr(lsp, lang, False)}


def enabled_languages() -> set[str]:
    """Resolve the LSP-enabled language set (see module docstring for order)."""
    env = _env_languages()
    if env:
        return env  # explicit override wins (back-compat)
    lsp = load_graph_indexing_config().lsp
    if lsp.mode == "off":
        return set()
    toggled = configured_languages()
    if lsp.mode == "on":
        return toggled
    # auto
    return toggled & detect_servers()


def is_language_enabled(language: str) -> bool:
    return language in enabled_languages()


def lsp_state() -> dict[str, object]:
    """State snapshot for status surfaces (``brainpalace status`` + Graph tab)."""
    lsp = load_graph_indexing_config().lsp
    via_env = bool(_env_languages())
    active: list[str] = sorted(enabled_languages())
    detected: list[str] = sorted(detect_servers())
    return {
        "mode": "env" if via_env else lsp.mode,
        "active": active,
        "detected": detected,
        "configured": sorted(configured_languages()),
        "via_env": via_env,
    }

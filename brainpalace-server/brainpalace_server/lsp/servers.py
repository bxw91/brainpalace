"""Per-language LSP server registry + gating (Phase 150).

Maps file extensions → language ids, language ids → launch commands, and reads
the opt-in ``BRAINPALACE_LSP_LANGUAGES`` allow-list. The whole subsystem is inert
unless a language is listed there; a missing server binary is handled by the
caller (fail-soft).
"""

from __future__ import annotations

import os

from brainpalace_server.config import settings

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


def language_for_path(path: str) -> str | None:
    """Return the LSP language id for a file path, or None if unsupported."""
    _, ext = os.path.splitext(path)
    return _EXT_LANGUAGE.get(ext.lower())


def enabled_languages() -> set[str]:
    """Parse ``BRAINPALACE_LSP_LANGUAGES`` (comma-separated) into a set.

    Empty by default → the entire LSP subsystem is inert.
    """
    raw = getattr(settings, "BRAINPALACE_LSP_LANGUAGES", "") or ""
    if not isinstance(raw, str):
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def is_language_enabled(language: str) -> bool:
    return language in enabled_languages()


def server_command(language: str) -> list[str] | None:
    """Launch command for a language's LSP server, or None if unknown."""
    cmd = _SERVER_COMMANDS.get(language)
    return list(cmd) if cmd else None

"""Adapter registry — slug → SessionToolAdapter."""

from __future__ import annotations

import logging
from pathlib import Path

from brainpalace_server.sessions.adapters.base import (
    SessionSource,
    SessionToolAdapter,
)

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, SessionToolAdapter] = {}


def register_adapter(adapter: SessionToolAdapter) -> None:
    """Register (or replace) an adapter under its slug."""
    _REGISTRY[adapter.slug] = adapter


def get_adapter(slug: str) -> SessionToolAdapter:
    """Return the adapter for ``slug``. Raises KeyError when unknown."""
    return _REGISTRY[slug]


def all_adapters() -> list[SessionToolAdapter]:
    """Every registered adapter, in registration order."""
    return list(_REGISTRY.values())


def resolve_session_sources(
    project_root: str,
    home: Path | None = None,
    tools: list[str] | None = None,
    tool_dirs: dict[str, str] | None = None,
) -> list[SessionSource]:
    """Every (adapter, directory) pair to sweep for this project.

    ``tools=None`` auto-detects: a tool is enabled when one of its source
    directories exists. Directory presence alone is the gate — an installed
    tool that was never run has no directory and costs nothing. An explicit
    list pins the selection (``[]`` disables all). ``tool_dirs`` overrides the
    resolved directory per slug.
    """
    home = home or Path.home()
    tool_dirs = tool_dirs or {}
    if tools is not None:
        for slug in tools:
            if slug not in _REGISTRY:
                # A typo here would otherwise SILENTLY disable a tool's archive.
                logger.warning(
                    "session_indexing.tools: unknown tool slug %r ignored "
                    "(known: %s)",
                    slug,
                    ", ".join(_REGISTRY),
                )
    wanted = (
        _REGISTRY
        if tools is None
        else {slug: _REGISTRY[slug] for slug in tools if slug in _REGISTRY}
    )

    sources: list[SessionSource] = []
    for slug, adapter in wanted.items():
        override = tool_dirs.get(slug)
        candidates = (
            [Path(override).expanduser()]
            if override
            else adapter.source_dirs(project_root, home)
        )
        for directory in candidates:
            if directory.exists():
                sources.append(SessionSource(adapter=adapter, directory=directory))
    return sources


__all__ = [
    "SessionSource",
    "SessionToolAdapter",
    "all_adapters",
    "get_adapter",
    "register_adapter",
    "resolve_session_sources",
]


def _load_builtin_adapters() -> None:
    """Import adapter modules for their registration side effect."""
    from brainpalace_server.sessions.adapters import (  # noqa: F401
        antigravity,
        claude_code,
        codex,
    )


_load_builtin_adapters()

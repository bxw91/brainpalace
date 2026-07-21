"""Single entry point for reading a transcript, whatever tool wrote it.

``indexing.session_loader.load_session`` is the CLAUDE CODE parser. Anything
that reads a transcript from the archive — indexing, distillation, scan mode —
must come through here instead, or a non-Claude-Code file parses to zero turns
and every caller degrades silently.
"""

from __future__ import annotations

import re
from pathlib import Path

from brainpalace_server.indexing.session_loader import SessionMeta, Turn
from brainpalace_server.sessions.adapters import get_adapter

#: Archive folders are ``YYYY-MM-DD-<tool>``; undated ones are ``undated-<tool>``.
#: The tool slug itself contains dashes ("claude-code"), so the date half is
#: matched exactly and everything after the separator is the slug.
_ARCHIVE_FOLDER_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|undated)-(?P<tool>.+)$")

DEFAULT_TOOL = "claude-code"


def tool_for_archived_path(path: str | Path) -> str | None:
    """Tool slug from an archived transcript's folder, or None.

    Walks ancestors so subagent transcripts nested under
    ``<folder>/<parent>/subagents/`` resolve to their parent folder's tool.
    """
    for parent in Path(path).parents:
        match = _ARCHIVE_FOLDER_RE.match(parent.name)
        if match:
            return match.group("tool")
    return None


def parse_transcript(
    path: str | Path,
    *,
    tool: str | None = None,
    text_trunc: int = 1500,
) -> tuple[SessionMeta, list[Turn]]:
    """Parse a transcript with the owning tool's adapter.

    ``tool`` is used when the caller knows it (the archive sweep does). When it
    is None the slug is inferred from the archive folder name. An unknown or
    unregistered slug falls back to Claude Code rather than raising — a parse
    that yields nothing is recoverable, an exception in the sweep is not.
    """
    slug = tool or tool_for_archived_path(path) or DEFAULT_TOOL
    try:
        adapter = get_adapter(slug)
    except KeyError:
        adapter = get_adapter(DEFAULT_TOOL)
    return adapter.parse(Path(path), text_trunc=text_trunc)


def title_for_transcript(path: str | Path, max_chars: int = 120) -> str | None:
    """Session title via the owning tool's adapter (folder-inferred).

    Same dispatch rule as :func:`parse_transcript`;
    ``first_user_prompt_line`` is the Claude Code implementation and must not
    be called directly on archived multi-tool paths.
    """
    slug = tool_for_archived_path(path) or DEFAULT_TOOL
    try:
        adapter = get_adapter(slug)
    except KeyError:
        adapter = get_adapter(DEFAULT_TOOL)
    return adapter.title(Path(path), max_chars=max_chars)

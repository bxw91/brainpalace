"""Claude Code adapter — the existing behaviour, behind the adapter seam.

Every function here delegates to the original implementations in
``indexing.session_loader`` / ``services.session_index_service`` so this move is
behaviour-preserving by construction.
"""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.indexing.session_loader import (
    SessionMeta,
    Turn,
    first_user_prompt_line,
    is_subagent_path,
    load_session,
    parent_session_id_for,
)
from brainpalace_server.sessions.adapters import register_adapter


class ClaudeCodeAdapter:
    """``~/.claude/projects/<cwd-with-slashes-as-dashes>/*.jsonl``."""

    slug = "claude-code"

    def source_dirs(self, project_root: str, home: Path) -> list[Path]:
        encoded = project_root.replace("/", "-")
        return [home / ".claude" / "projects" / encoded]

    def discover(self, src: Path, project_root: str) -> list[Path]:
        if not src.exists():
            return []
        files = sorted(src.glob("*.jsonl"))
        files += sorted(src.glob("*/subagents/*.jsonl"))
        return files

    def owns(self, path: Path, project_root: str) -> bool:
        # The directory IS the project (path-encoded cwd), so anything
        # discovered under it belongs here by construction.
        return True

    def parse(
        self, path: Path, *, text_trunc: int = 1500
    ) -> tuple[SessionMeta, list[Turn]]:
        meta, turns = load_session(path, text_trunc=text_trunc)
        meta.tool = self.slug
        return meta, turns

    def title(self, path: Path, max_chars: int = 120) -> str | None:
        return first_user_prompt_line(path, max_chars=max_chars)

    def is_subagent(self, path: Path) -> bool:
        return is_subagent_path(path)

    def parent_session_id(self, path: Path) -> str | None:
        return parent_session_id_for(path)


register_adapter(ClaudeCodeAdapter())

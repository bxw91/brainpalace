"""Durable raw-transcript archive for session indexing.

Copies live Claude transcripts (~/.claude/projects/<enc>/*.jsonl) verbatim into
a gitignored, dated archive under .brainpalace/, maintains a manifest and
tombstones, and is the source the index reads from. ~/.claude is read-only.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from brainpalace_server.config.session_config import DEFAULT_TOOL
from brainpalace_server.indexing.session_loader import (
    is_subagent_path,
    load_session,
    parent_session_id_for,
)

logger = logging.getLogger(__name__)


class SessionArchiveService:
    """File + state layer for the raw session archive (no indexing here).

    Archive date folders are tool-tagged ``YYYY-MM-DD-<tool>`` (e.g.
    ``2026-06-01-claude-code``) so same-day sessions from different tools sort
    adjacently. The ``tool`` is also stored as a structured manifest field —
    that field, not the path, is the source of truth for consumers.
    """

    def __init__(self, archive_dir: str | Path, tool: str = DEFAULT_TOOL) -> None:
        self.archive_dir = Path(archive_dir)
        self.tool = tool
        self._manifest_path = self.archive_dir / "manifest.json"
        self._tombstone_path = self.archive_dir / "tombstones.json"
        self._manifest: dict[str, dict[str, Any]] = self._load(self._manifest_path)
        self._tombstones: dict[str, dict[str, Any]] = self._load(self._tombstone_path)

    @staticmethod
    def _load(path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Archive state %s unreadable, treating as empty: %s", path.name, exc
            )
            return {}

    def _save(self, path: Path, data: dict[str, dict[str, Any]]) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    # --- tombstones ---
    def is_tombstoned(self, session_id: str) -> bool:
        return session_id in self._tombstones

    def tombstone(self, session_id: str, origin_path: str) -> None:
        from datetime import datetime, timezone

        self._tombstones[session_id] = {
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "origin_path": origin_path,
        }
        self._save(self._tombstone_path, self._tombstones)

    # --- manifest ---
    def manifest_entry(self, session_id: str) -> dict[str, Any] | None:
        return self._manifest.get(session_id)

    def _put_manifest(self, session_id: str, entry: dict[str, Any]) -> None:
        self._manifest[session_id] = entry
        self._save(self._manifest_path, self._manifest)

    def _drop_manifest(self, session_id: str) -> None:
        if session_id in self._manifest:
            del self._manifest[session_id]
            self._save(self._manifest_path, self._manifest)

    # --- sync ---

    @staticmethod
    def _date_for(started_at: str | None) -> str:
        """Extract YYYY-MM-DD from an ISO timestamp, or return 'undated'."""
        if started_at and len(started_at) >= 10 and started_at[4] == "-":
            return started_at[:10]
        return "undated"

    def _folder_for(self, date: str) -> str:
        """Tool-tagged date folder segment, e.g. ``2026-06-01-claude-code``."""
        return f"{date}-{self.tool}"

    @staticmethod
    def _manifest_key(live_path: Path, session_id: str) -> str:
        """Unique manifest key per transcript FILE.

        Subagent transcripts carry the *parent's* ``sessionId``, so keying the
        manifest by ``session_id`` alone collides a parent with its subagents
        (last write wins, clobbering the parent entry). Subagents therefore get
        a composite ``<parent_id>/<agent_stem>`` key; top-level transcripts key
        by their own session_id. The purge ``session_id`` is stored in the entry.
        """
        if is_subagent_path(live_path):
            parent_id = parent_session_id_for(live_path) or "unknown-parent"
            return f"{parent_id}/{live_path.stem}"
        return session_id

    def _dest_for(self, live_path: Path, session_id: str, folder: str) -> Path:
        """Archive destination, preserving subagent structure under parent folder.

        ``folder`` is the tool-tagged ``YYYY-MM-DD-<tool>`` segment. Subagents
        nest under their parent's *recorded* folder (``archived_dir``) so a
        parent indexed under one tool keeps its children together.
        """
        if is_subagent_path(live_path):
            parent_id = parent_session_id_for(live_path) or "unknown-parent"
            parent_entry = self.manifest_entry(parent_id)
            parent_folder = (
                parent_entry.get("archived_dir") if parent_entry else None
            ) or folder
            return (
                self.archive_dir
                / parent_folder
                / parent_id
                / "subagents"
                / live_path.name
            )
        return self.archive_dir / folder / f"{session_id}.jsonl"

    def sync(self, live_path: str | Path) -> Path | None:
        """Copy a live transcript into the archive. Returns archive path or None.

        Returns None when the session is tombstoned (curated away) or the file
        cannot be read. Returns the existing archive path without re-copying when
        the file is unchanged (mtime + size match).
        """
        live_path = Path(live_path)
        try:
            meta, _turns = load_session(live_path)
        except (OSError, ValueError) as exc:
            logger.warning("Cannot read transcript %s: %s", live_path, exc)
            return None
        session_id = meta.session_id or live_path.stem
        key = self._manifest_key(live_path, session_id)

        if self.is_tombstoned(key):
            return None

        try:
            stat = live_path.stat()
        except OSError:
            return None

        entry = self.manifest_entry(key)
        if (
            entry
            and entry.get("src_mtime") == stat.st_mtime
            and entry.get("src_size") == stat.st_size
        ):
            return Path(entry["archive_path"])  # unchanged: no re-copy

        date = self._date_for(meta.started_at)
        folder = self._folder_for(date)
        dest = self._dest_for(live_path, session_id, folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live_path, dest)  # copy2 preserves mtime

        self._put_manifest(
            key,
            {
                "session_id": session_id,
                "origin_path": str(live_path),
                "archive_path": str(dest),
                "archived_date": date,
                "archived_dir": folder,
                "tool": self.tool,
                "src_mtime": stat.st_mtime,
                "src_size": stat.st_size,
            },
        )
        return dest

    def stats(self) -> dict[str, Any]:
        archived_bytes = 0
        sessions: set[str] = set()
        for entry in self._manifest.values():
            sid = entry.get("session_id")
            if sid:
                sessions.add(sid)
            p = Path(entry.get("archive_path", ""))
            if p.exists():
                archived_bytes += p.stat().st_size
        return {
            # Distinct sessions (parent + its subagents count as one session).
            "archived_sessions": len(sessions),
            # Total archived transcript files (one manifest entry each).
            "archived_files": len(self._manifest),
            "tombstoned": len(self._tombstones),
            "archived_bytes": archived_bytes,
        }

    def backfill(self, live_paths: Iterable[str | Path]) -> list[Path]:
        produced: list[Path] = []
        for live in live_paths:
            archive_path = self.sync(live)
            if archive_path is not None:
                produced.append(archive_path)
        return produced

    def reconcile_deletions(self) -> list[str]:
        """Tombstone + drop manifest entries whose archive FILE is gone.

        Manifest keys are per-file; a single ``session_id`` may map to several
        files (a top-level transcript plus its subagents, which share the
        parent's sessionId). A session_id is returned for purging only when
        *all* of its files are gone — so deleting one subagent never purges the
        still-present parent's chunks. Tombstones are per-file (by manifest key)
        so a curated-away file is not re-synced while its siblings remain.
        """
        gone: list[str] = []  # session_ids of dropped files
        for key, entry in list(self._manifest.items()):
            if not Path(entry.get("archive_path", "")).exists():
                gone.append(entry.get("session_id", ""))
                self.tombstone(key, origin_path=entry.get("origin_path", ""))
                self._drop_manifest(key)
        surviving = {e.get("session_id") for e in self._manifest.values()}
        purge: list[str] = []
        for session_id in gone:
            if session_id and session_id not in surviving and session_id not in purge:
                purge.append(session_id)
        return purge

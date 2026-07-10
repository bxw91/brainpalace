"""Cross-session linking (Phase 140).

Runs after ``/sessions/extract`` persists a session's chunks + triplets. Three
jobs, all best-effort (never fail extraction):

1. **Canonicalise** file-like entities (project-root-relative POSIX paths) so the
   graph keeps one node per real file instead of ``auth.py`` / ``./auth.py`` /
   ``/abs/auth.py`` duplicates. Non-path entities pass through untouched.
2. **Supersession** — when a decision supersedes a prior one, close the prior
   decision's still-valid *facts* (via the temporal graph's ``timeline`` +
   ``invalidate``) so stale advice drops out of default queries, while the
   ``superseded-by`` history edge is preserved for ``as_of`` / ``timeline``.
3. **Promotion** — promote durable, rationale-backed current decisions into the
   030 curated-memory markdown namespace (closing the sessions → memory loop).

Temporal supersession only has effect on the SQLite graph backend (090); on the
in-memory ``simple`` backend the graph lacks the temporal surface and these
calls no-op.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brainpalace_server.services.memory_service import MemoryCapError

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Entities that look like source files get canonicalised; everything else
# (free-text concepts, decisions) is left alone.
_CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".kt",
    ".swift",
    ".php",
    ".scala",
    ".md",
    ".rst",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".ini",
    ".cfg",
    ".sh",
    ".sql",
    ".html",
    ".css",
}


def _looks_like_path(name: str) -> bool:
    if "/" in name or "\\" in name:
        return True
    _, ext = os.path.splitext(name)
    return ext.lower() in _CODE_EXTS


def canonicalize_entity(name: str, project_root: str) -> str:
    """Normalise a file-like entity to a project-root-relative POSIX path.

    Non-path entities, paths outside the project root, and the empty-root case
    are returned unchanged (never guess).
    """
    if not name or not project_root or not _looks_like_path(name):
        return name
    root = os.path.normpath(project_root)
    absp = (
        os.path.normpath(name)
        if os.path.isabs(name)
        else os.path.normpath(os.path.join(root, name))
    )
    try:
        rel = os.path.relpath(absp, root)
    except ValueError:  # e.g. different drive on Windows
        return name
    if rel.startswith(".."):  # outside the project root
        return name
    return rel.replace(os.sep, "/")


def _supersession_pairs(payload: Any) -> list[tuple[str, str]]:
    """Collect (old, new) decision pairs from the payload."""
    pairs: list[tuple[str, str]] = []
    for d in payload.decisions:
        if getattr(d, "supersedes", None):
            pairs.append((d.supersedes, d.text))
    for t in payload.triplets:
        if t.relation == "superseded-by":
            pairs.append((t.subject, t.object))
    return pairs


def apply_supersessions(payload: Any, graph: Any, project_root: str = "") -> int:
    """Close superseded decisions' stale facts; preserve supersedes history.

    Returns the number of prior decisions whose facts were invalidated. No-op
    (0) when the graph lacks the temporal surface (e.g. simple backend).
    """
    if graph is None or not all(
        hasattr(graph, m) for m in ("find_decision_nodes", "timeline", "invalidate")
    ):
        return 0

    count = 0
    for old, _new in _supersession_pairs(payload):
        old_c = canonicalize_entity(old, project_root)
        if not graph.find_decision_nodes(old_c):
            continue
        invalidated_here = False
        for edge in graph.timeline(old_c):
            if not edge.get("valid"):
                continue
            # Preserve the supersedes history edge — it documents the chain.
            if edge.get("predicate") == "superseded-by":
                continue
            try:
                if graph.invalidate(edge["subject"], edge["predicate"], edge["object"]):
                    invalidated_here = True
            except Exception as exc:  # noqa: BLE001 — best-effort
                logger.debug("invalidate failed: %s", exc)
        if invalidated_here:
            count += 1
    return count


async def promote_decisions(
    payload: Any,
    memory_service: Any,
    sensitivity: str = "normal",
    state_dir: Path | None = None,
) -> int:
    """Promote durable current decisions into curated memory (030).

    Uses the reclaim-aware write path so a full memory file evicts stale
    auto-promoted entries (and obsoletes cross-session superseded ones) instead
    of silently dropping new decisions. If the file is full of protected manual
    facts, a cap-pressure marker is written (surfaced by ``status``) rather than
    swallowed at DEBUG.
    """
    if memory_service is None:
        return 0

    superseded_now = {
        d.supersedes for d in payload.decisions if getattr(d, "supersedes", None)
    }
    promoted = 0
    skipped_cap = 0
    for d in payload.decisions:
        if not getattr(d, "rationale", None):
            continue
        if d.text in superseded_now:
            continue
        text = d.text + (f" — {d.rationale}" if d.rationale else "")
        try:
            await memory_service.add(
                text,
                tags=["session-decision"],
                origin=f"session:{payload.session_id}",
                sensitivity=sensitivity,
                reclaim=True,
                supersedes=getattr(d, "supersedes", None),
            )
            promoted += 1
        except MemoryCapError as exc:
            skipped_cap += 1
            logger.warning("decision promotion skipped (memory cap full): %s", exc)
        except Exception as exc:  # noqa: BLE001 — dup/etc are non-fatal
            logger.warning(
                "decision promotion skipped (%s): %s", type(exc).__name__, exc
            )

    if state_dir is not None:
        marker = state_dir / "memory_cap_pressure.json"
        try:
            if skipped_cap:
                marker.write_text(
                    json.dumps({"at": _now_iso(), "skipped": skipped_cap})
                )
            elif marker.exists():
                # Pressure relieved (a promotion succeeded) → clear the stale
                # warning so `status` doesn't show it forever.
                marker.unlink()
        except Exception as exc:  # noqa: BLE001 — marker is best-effort
            logger.debug("cap-pressure marker update failed: %s", exc)
    return promoted

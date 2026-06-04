"""Phase 080 — server-side session distiller (the *provider* engine).

This engine is **doubly opt-in**: (1) the default ``mode: subagent`` summarizes
only inside Claude Code and never invokes this module, and (2) the provider
distiller is **disabled by default** — it runs only when ``SESSION_DISTILL_ENABLED``
is set truthy. Both locks must be lifted: ``mode: provider``/``auto`` **and**
``SESSION_DISTILL_ENABLED=true``. Then the server distils each archived transcript
into a :class:`SessionExtraction` using the configured summarization provider
(Ollama free / cloud metered), persisting it via the same
:class:`SessionExtractService` the plugin path uses.

THE GUARANTEE (only when both locks are lifted): within ``provider``/``auto`` +
``SESSION_DISTILL_ENABLED=true``, every session is summarized — there is **no code
path that silently skips a session**. The non-summarize paths are ``mode !=
provider`` (which includes the default ``subagent``) and the default-off
``SESSION_DISTILL_ENABLED`` switch — both applied by the *caller* (lifespan), so
this module, once invoked, only ever *succeeds-and-marks* or
*fails-and-leaves-unmarked* (to be retried by catch-up).

Execution model (Task 0-C: no periodic scheduler exists): real-time distills run
behind a bounded :class:`asyncio.Semaphore` so the watcher never blocks; the
catch-up sweep (server startup + after each archive) re-distils any quiescent,
un-marked transcript — recovering large/failed/restarted/old sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from brainpalace_server.indexing.session_loader import SessionMeta, Turn, load_session
from brainpalace_server.models.session_extract import (
    SessionExtraction,
    SessionExtractResult,
)
from brainpalace_server.services.session_extract_service import SessionExtractService

logger = logging.getLogger(__name__)

#: A finished transcript is "quiescent" after this many idle seconds (default
#: 5 min) — or immediately if a newer session file exists for the project.
DEFAULT_IDLE_SECONDS = 300

#: Char budget per ``generate()`` call. Filtered text above this is split into
#: parts, each summarized, then hierarchically merged (never skipped).
DEFAULT_CHUNK_CHARS = 48000

#: Per-session success marker dir under the project state dir.
_MARKER_SUBDIR = "extracted"


class Summarizer(Protocol):
    """The one method the distiller needs from a summarization provider."""

    async def generate(self, prompt: str) -> str: ...


# --------------------------------------------------------------------------- #
# Shared moderate filter (Task 7 contract). `load_session` already keeps
# user/assistant + condensed thinking + tool_use(name+key inputs) + truncated
# tool_result and drops attachments/file-history/queue-ops; we render its turns.
# --------------------------------------------------------------------------- #
def render_turns(turns: list[Turn]) -> str:
    """Render loader turns into a compact plain-text transcript."""
    lines: list[str] = []
    for t in turns:
        if t.kind == "tool_use":
            inp = ", ".join(f"{k}={v}" for k, v in t.tool_inputs.items())
            lines.append(f"[{t.index}] {t.role} tool_use {t.tool_name}({inp})")
        elif t.kind == "tool_result":
            lines.append(f"[{t.index}] {t.role} tool_result: {t.text}")
        elif t.kind == "thinking":
            lines.append(f"[{t.index}] {t.role} thinking: {t.text}")
        else:
            lines.append(f"[{t.index}] {t.role}: {t.text}")
    return "\n".join(lines)


def filter_transcript(path: str | Path) -> str:
    """Moderate-filtered plain-text rendering of a transcript (shared contract).

    Single source of truth for what the provider engine feeds the LLM; the
    plugin's ``chat-session-extractor`` agent prompt mirrors this contract (see
    docs/SESSION_INDEXING.md → "Session filter contract").
    """
    _meta, turns = load_session(path)
    return render_turns(turns)


def _session_id(meta: SessionMeta, path: str | Path) -> str:
    """Stable id for marker/keying — transcript ``sessionId`` else file stem."""
    return meta.session_id or Path(path).stem


# --------------------------------------------------------------------------- #
# Success marker (Task 0-E)
# --------------------------------------------------------------------------- #
def marker_path(project_root: str | Path, session_id: str) -> Path:
    return Path(project_root) / ".brainpalace" / _MARKER_SUBDIR / f"{session_id}.done"


def is_marked(project_root: str | Path, session_id: str) -> bool:
    return marker_path(project_root, session_id).exists()


def write_marker(project_root: str | Path, session_id: str) -> None:
    mp = marker_path(project_root, session_id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Quiescence gate (Task 0 Step 3) — never distil the live session
# --------------------------------------------------------------------------- #
def is_quiescent(
    path: str | Path,
    *,
    idle_seconds: int = DEFAULT_IDLE_SECONDS,
    now: float | None = None,
    newer_exists: bool = False,
) -> bool:
    """True when ``path`` is safe to distil (finished, not actively growing)."""
    if newer_exists:
        return True
    now = time.time() if now is None else now
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return False
    return (now - mtime) >= idle_seconds


def pending_sessions(
    project_root: str | Path,
    archive_dir: str | Path,
    *,
    idle_seconds: int = DEFAULT_IDLE_SECONDS,
    now: float | None = None,
) -> list[tuple[str, str]]:
    """Archived sessions that still need (re-)summarizing.

    A session is pending when its archived file is **quiescent** (idle ≥
    ``idle_seconds`` — not actively growing) AND it is either unmarked or its
    archive file is **newer than its ``.done`` marker** (new write, or a resumed
    transcript that grew since the last summary). Returns ``(session_id,
    archive_path)`` pairs.
    """
    from .session_archive_service import SessionArchiveService

    now = time.time() if now is None else now
    svc = SessionArchiveService(archive_dir)
    pending: list[tuple[str, str]] = []
    for sid, archive_path, _src_mtime in svc.iter_sessions():
        if not archive_path.is_file():
            continue
        if not is_quiescent(archive_path, idle_seconds=idle_seconds, now=now):
            continue
        mp = marker_path(project_root, sid)
        try:
            if not mp.exists():
                needs = True
            else:
                needs = archive_path.stat().st_mtime > mp.stat().st_mtime
        except OSError:
            needs = True
        if needs:
            pending.append((sid, str(archive_path)))
    return pending


# --------------------------------------------------------------------------- #
# Prompt + JSON parsing
# --------------------------------------------------------------------------- #
_SCHEMA = (
    "Return ONLY one JSON object — no prose, no markdown fences. Exact keys:\n"
    '{"summary": "<=120 words, what was accomplished",\n'
    ' "open_threads": ["..."],\n'
    ' "decisions": [{"text": "...", "rationale": "... or null",'
    ' "files": ["..."], "supersedes": "prior decision text or null"}],\n'
    ' "files_touched": [{"path": "...", "action": "edit|create|read"}],\n'
    ' "tools_used": ["..."],\n'
    ' "triplets": [{"subject": "...", "relation":'
    ' "touches|fixed-by|superseded-by|ran-in|depends-on|decided",'
    ' "object": "...", "evidence_turn": null}]}\n'
    "Do NOT invent any other keys. Omit session_id/branch/timestamps — those are"
    " filled by the server."
)


def build_prompt(filtered_text: str, *, reminder: bool = False, part: str = "") -> str:
    head = "Distil this finished AI coding session into durable knowledge."
    if part:
        head = (
            f"Distil PART {part} of a finished AI coding session. Capture only "
            "what this part shows; a later pass will merge parts."
        )
    rem = (
        "\nIMPORTANT: your previous reply was not valid. Return ONLY valid JSON "
        "with exactly the keys below, nothing else.\n"
        if reminder
        else "\n"
    )
    return f"{head}{rem}{_SCHEMA}\n\n--- TRANSCRIPT ---\n{filtered_text}"


def build_merge_prompt(partials: list[str]) -> str:
    joined = "\n\n--- PARTIAL ---\n".join(partials)
    return (
        "Merge these partial distillations of ONE session into a single final "
        "object. Deduplicate decisions/triplets; keep the most important. "
        f"{_SCHEMA}\n\n--- PARTIALS ---\n{joined}"
    )


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a model reply (tolerates fences/prose)."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_extraction(
    raw: str, meta: SessionMeta, session_id: str
) -> SessionExtraction | None:
    """Parse a model reply into a validated :class:`SessionExtraction`.

    Filters to known top-level keys (so a stray key never drops a whole session)
    and injects server-owned provenance from ``meta``. Returns ``None`` on
    unparseable/invalid output → the caller retries / leaves it unmarked.
    """
    obj = _extract_json(raw)
    if obj is None:
        return None
    fields = {k: v for k, v in obj.items() if k in SessionExtraction.model_fields}
    fields["session_id"] = session_id
    fields["project_path"] = meta.project_path
    fields["branch"] = meta.branch
    fields["started_at"] = meta.started_at
    fields["ended_at"] = meta.ended_at
    try:
        return SessionExtraction(**fields)
    except ValidationError as exc:
        logger.debug("session extraction validation failed (%s): %s", session_id, exc)
        return None


async def _generate(summarizer: Summarizer, prompt: str) -> str | None:
    """Call ``generate`` with one transient-error retry. None ⇒ both failed."""
    for attempt in (1, 2):
        try:
            return await summarizer.generate(prompt)
        except Exception as exc:  # noqa: BLE001 — transient provider error
            logger.warning("summarizer.generate failed (attempt %d): %s", attempt, exc)
    return None


def _split(text: str, chunk_chars: int) -> list[str]:
    """Split filtered text into ≤``chunk_chars`` parts on line boundaries."""
    parts: list[str] = []
    cur: list[str] = []
    size = 0
    for line in text.split("\n"):
        if size + len(line) + 1 > chunk_chars and cur:
            parts.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    return parts or [text]


async def _run_extraction(
    summarizer: Summarizer,
    text: str,
    meta: SessionMeta,
    session_id: str,
    chunk_chars: int,
) -> SessionExtraction | None:
    """Single-pass for small transcripts; chunk + hierarchical merge for big."""
    if len(text) <= chunk_chars:
        raw = await _generate(summarizer, build_prompt(text))
        if raw is None:
            return None  # provider failed after retry → unmarked, catch-up retries
        payload = parse_extraction(raw, meta, session_id)
        if payload is not None:
            return payload
        # Got text but it did not parse/validate → one reminder retry.
        raw = await _generate(summarizer, build_prompt(text, reminder=True))
        return parse_extraction(raw, meta, session_id) if raw is not None else None

    parts = _split(text, chunk_chars)
    partials: list[str] = []
    for i, part in enumerate(parts, 1):
        raw = await _generate(summarizer, build_prompt(part, part=f"{i}/{len(parts)}"))
        if raw is None:
            return None  # a part failed twice → unmarked, catch-up retries
        partials.append(raw)
    merged = await _generate(summarizer, build_merge_prompt(partials))
    if merged is None:
        return None
    payload = parse_extraction(merged, meta, session_id)
    if payload is not None:
        return payload
    merged = await _generate(
        summarizer, build_merge_prompt(partials) + "\nReturn ONLY valid JSON."
    )
    return parse_extraction(merged, meta, session_id) if merged is not None else None


async def distill_transcript(
    path: str | Path,
    *,
    summarizer: Summarizer,
    embedder: Any,
    storage_backend: Any,
    project_root: str,
    graph_store: Any | None = None,
    memory_service: Any | None = None,
    digest_path: str | Path | None = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
) -> SessionExtractResult | None:
    """Distil one transcript → store → mark. Returns the store result or None.

    Never raises: any failure (provider down, malformed output, oversized merge
    failure) returns ``None`` and leaves the session **un-marked** so the
    catch-up sweep retries it. A success writes the ``.done`` marker last.
    """
    meta, turns = load_session(path)
    sid = _session_id(meta, path)
    text = render_turns(turns)
    if not text.strip():
        # Degenerate/empty transcript — nothing to summarize. Mark so it is not
        # reprocessed forever (this is not a "skip": there is no content).
        write_marker(project_root, sid)
        return None

    try:
        payload = await _run_extraction(summarizer, text, meta, sid, chunk_chars)
        if payload is None:
            return None  # unmarked → retried by catch-up
        result = await SessionExtractService().store(
            payload,
            embedder=embedder,
            storage_backend=storage_backend,
            graph_store=graph_store,
            digest_path=digest_path,
            memory_service=memory_service,
            project_root=project_root,
        )
    except Exception as exc:  # noqa: BLE001 — never propagate into the watcher
        logger.warning("distill failed for %s: %s", path, exc)
        return None

    write_marker(project_root, sid)
    return result


class SessionDistiller:
    """Gated, bounded wrapper around :func:`distill_transcript` for the watcher.

    Constructed in lifespan when ``mode in (provider, auto)`` and the kill switch
    is on. In ``auto`` mode it self-reconciles per distil: when the plugin is
    present it defers (the plugin's subagent owns extraction), UNLESS the session
    is un-marked AND older than ``grace_hours`` (a disabled/never-reopened plugin
    safety net). Applies the marker dedup + quiescence gate, runs distills behind
    a semaphore, and never lets an exception escape into the watcher loop.
    """

    def __init__(
        self,
        *,
        summarizer: Summarizer,
        embedder: Any,
        storage_backend: Any,
        project_root: str,
        graph_store: Any | None = None,
        memory_service: Any | None = None,
        digest_path: str | Path | None = None,
        idle_seconds: int = DEFAULT_IDLE_SECONDS,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        max_concurrent: int = 2,
        mode: str = "provider",
        plugin_present: Callable[[], bool] | None = None,
        grace_hours: float = 24.0,
    ) -> None:
        self.summarizer = summarizer
        self.embedder = embedder
        self.storage_backend = storage_backend
        self.project_root = project_root
        self.graph_store = graph_store
        self.memory_service = memory_service
        self.digest_path = digest_path
        self.idle_seconds = idle_seconds
        self.chunk_chars = chunk_chars
        self._sem = asyncio.Semaphore(max_concurrent)
        self.mode = mode
        self._plugin_present = plugin_present or (lambda: False)
        self.grace_seconds = grace_hours * 3600

    async def maybe_distill(
        self,
        path: str | Path,
        *,
        newer_exists: bool = False,
        force: bool = False,
    ) -> SessionExtractResult | None:
        """Distil ``path`` if un-marked + quiescent; else defer (return None).

        ``force`` (on-demand backfill) bypasses the marker dedup AND the
        quiescence gate — re-distilling even an already-marked session.
        """
        meta, _turns = load_session(path)
        sid = _session_id(meta, path)
        if self.mode == "auto" and self._plugin_present():
            # Plugin owns extraction (subagent). Defer — UNLESS the session is
            # un-marked AND older than the grace window (disabled/never-reopened
            # plugin safety net). Idempotent + unified marker => no double-run.
            if is_marked(self.project_root, sid):
                return None
            try:
                age = time.time() - Path(path).stat().st_mtime
            except OSError:
                return None
            if age < self.grace_seconds:
                return None  # fresh — let the subagent handle it
            # else: fall through and distil (safety net)
        if not force:
            if is_marked(self.project_root, sid):
                return None
            if not is_quiescent(
                path, idle_seconds=self.idle_seconds, newer_exists=newer_exists
            ):
                return None  # live/active transcript — deferred, NOT dropped
        async with self._sem:
            # Re-check after acquiring: a concurrent run may have just marked it.
            if not force and is_marked(self.project_root, sid):
                return None
            return await distill_transcript(
                path,
                summarizer=self.summarizer,
                embedder=self.embedder,
                storage_backend=self.storage_backend,
                project_root=self.project_root,
                graph_store=self.graph_store,
                memory_service=self.memory_service,
                digest_path=self.digest_path,
                chunk_chars=self.chunk_chars,
            )

    async def _safe(self, path: str | Path, newer_exists: bool, force: bool) -> None:
        try:
            await self.maybe_distill(path, newer_exists=newer_exists, force=force)
        except Exception as exc:  # noqa: BLE001 — background task, never crash
            logger.warning("scheduled distill crashed for %s: %s", path, exc)

    def schedule(
        self, path: str | Path, *, newer_exists: bool = False, force: bool = False
    ) -> Any:
        """Fire-and-forget a bounded distill. Never blocks the caller."""
        return asyncio.create_task(self._safe(path, newer_exists, force))

    async def catch_up(self, transcripts: list[Path]) -> int:
        """Sweep: distil every quiescent, un-marked transcript. Returns count.

        The most recently modified file uses the idle gate (it may be live); all
        older ones are treated as quiescent (a newer session exists).
        """
        if not transcripts:
            return 0
        ordered = sorted(transcripts, key=lambda p: _safe_mtime(p), reverse=True)
        done = 0
        for i, p in enumerate(ordered):
            newer = i > 0  # everything after the newest has a newer sibling
            if await self.maybe_distill(p, newer_exists=newer) is not None:
                done += 1
        return done


def _safe_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0

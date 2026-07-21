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
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from brainpalace_server.indexing.session_loader import SessionMeta, Turn
from brainpalace_server.models.session_extract import (
    SessionExtraction,
    SessionExtractResult,
)
from brainpalace_server.services.auto_grace import (
    provider_auto_eligible,
    read_last_drain,
)
from brainpalace_server.services.session_extract_service import SessionExtractService
from brainpalace_server.sessions.parse import parse_transcript

logger = logging.getLogger(__name__)

#: A finished transcript is "quiescent" after this many idle seconds (default
#: 5 min) — or immediately if a newer session file exists for the project.
DEFAULT_IDLE_SECONDS = 300

#: Char budget per ``generate()`` call. Filtered text above this is split into
#: parts, each summarized, then hierarchically merged (never skipped).
DEFAULT_CHUNK_CHARS = 48000

#: Per-session success marker dir under the project state dir.
_MARKER_SUBDIR = "extracted"

#: Progress-sidecar schema version (2b-4). Bump when the on-disk shape changes;
#: read_progress tolerates legacy (no "v") sidecars and declines unknown future
#: versions (re-distill) so a model/format change is a migration, not a silent
#: fleet-wide full re-distill.
_SIDECAR_VERSION = 1


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
    _meta, turns = parse_transcript(path)
    return render_turns(turns)


def _session_id(meta: SessionMeta, path: str | Path) -> str:
    """Stable id for marker/keying — transcript ``sessionId`` else file stem."""
    return meta.session_id or Path(path).stem


# --------------------------------------------------------------------------- #
# Atomic state writes (finding 2b-1) — a crash/disk-full mid-write must never
# leave a truncated marker/sidecar (which read_progress would treat as absent →
# full re-distill). Write a sibling temp then os.replace (atomic on POSIX).
# --------------------------------------------------------------------------- #
def _atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(data, encoding=encoding)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)  # never leave residue on failure
        raise


# --------------------------------------------------------------------------- #
# Per-session distill lock (finding 2b-3) — the reconciler tick and the catch_up
# fallback can distill the same session concurrently. distil is a read-modify-
# write (read_progress → extract → merge → write_progress); without a mutex both
# read the same prior, both pay the LLM, and the later write loses the other's
# advance (re-distilling those turns next time). Serialize per session so the
# second caller re-reads the advanced offset and no-ops. Keyed by
# (project_root, session_id); the server runs a single event loop.
# --------------------------------------------------------------------------- #
_distill_locks: dict[str, asyncio.Lock] = {}


def _distill_lock(project_root: str | Path, session_id: str) -> asyncio.Lock:
    key = f"{project_root}\x00{session_id}"
    lock = _distill_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _distill_locks[key] = lock
    return lock


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
    _atomic_write_text(mp, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# --------------------------------------------------------------------------- #
# Progress sidecar (Task Plan-2b: incremental resume)
# --------------------------------------------------------------------------- #
def progress_path(project_root: str | Path, session_id: str) -> Path:
    return (
        Path(project_root)
        / ".brainpalace"
        / _MARKER_SUBDIR
        / f"{session_id}.progress.json"
    )


def read_progress(
    project_root: str | Path, session_id: str
) -> tuple[int, SessionExtraction] | None:
    """Return (last_offset, prior_extraction) or None if absent/unreadable."""
    p = progress_path(project_root, session_id)
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        v = obj.get("v")  # 2b-4: legacy sidecars have no "v"; treat as current
        if v is not None and v > _SIDECAR_VERSION:
            return None  # unknown future format — re-distill rather than misread
        offset = int(obj["offset"])
        extraction = SessionExtraction.model_validate(obj["extraction"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return offset, extraction


def prune_orphan_sidecars(project_root: str | Path, known_session_ids: set[str]) -> int:
    """Delete ``*.progress.json`` resume sidecars whose session is gone (2b-6).

    A sidecar is orphaned when its session_id is not in ``known_session_ids``
    (no live/archived transcript). ``.done`` markers are deliberately left alone:
    deleting a marker would force a costly full re-distill, so the disk saved is
    not worth the risk. Best-effort — unreadable entries are skipped. Returns the
    count removed."""
    d = Path(project_root) / ".brainpalace" / _MARKER_SUBDIR
    if not d.is_dir():
        return 0
    suffix = ".progress.json"
    removed = 0
    for f in d.glob(f"*{suffix}"):
        sid = f.name[: -len(suffix)]
        if sid in known_session_ids:
            continue
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def write_progress(
    project_root: str | Path,
    session_id: str,
    offset: int,
    extraction: SessionExtraction,
) -> None:
    p = progress_path(project_root, session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        p,
        json.dumps(
            {
                "v": _SIDECAR_VERSION,
                "offset": offset,
                "extraction": extraction.model_dump(mode="json"),
            }
        ),
    )


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
    ' "object": "...", "evidence_turn": null}],\n'
    ' "records": [{"subject": "...", "metric": "...", "value": 0,'
    ' "unit": "... or null", "ts": "ISO8601 or null"}]  (use [] if the'
    " session has no measurements — do not invent records)}\n"
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


def _dedup_preserve(items: list[Any], key: Callable[[Any], Any]) -> list[Any]:
    """First-wins dedup that preserves order (prior entries before new ones)."""
    seen: set[Any] = set()
    out: list[Any] = []
    for it in items:
        k = key(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def merge_extractions(
    prior: SessionExtraction,
    new: SessionExtraction,
    session_id: str,
) -> SessionExtraction:
    """Structurally merge a prior extraction with a new-turns extraction — **no LLM**
    (finding 2b-2).

    Resume previously re-ran an LLM merge of ``prior ⊕ new`` on every drain; since
    ``prior`` is itself already merged, a long session's summary/decisions/triplets
    passed through N successive lossy re-summarizations that could paraphrase away
    or drop earlier content. Instead, set-union the structured fields with stable
    dedup keys (lossless, free) and join the prose summaries without a model call.
    Resume-only — never called on a fresh session, so non-resume output is
    unchanged. Always returns a value (no provider failure path)."""
    # Summary: `new` summarizes only the new turns; `prior` covers everything
    # before. Concatenate the (non-duplicate) parts so nothing is re-summarized
    # away — bounded growth (one delta per resume), never a lossy re-derivation.
    merged_summary = ""
    for s in (prior.summary, new.summary):
        s = (s or "").strip()
        if s and s not in merged_summary:
            merged_summary = s if not merged_summary else f"{merged_summary}\n\n{s}"

    decisions = _dedup_preserve(
        [*prior.decisions, *new.decisions], key=lambda d: d.text.strip().lower()
    )
    triplets = _dedup_preserve(
        [*prior.triplets, *new.triplets],
        key=lambda t: (
            t.subject.strip().lower(),
            t.relation,
            t.object.strip().lower(),
        ),
    )
    open_threads = _dedup_preserve(
        [*prior.open_threads, *new.open_threads], key=lambda s: s.strip().lower()
    )
    tools_used = _dedup_preserve(
        [*prior.tools_used, *new.tools_used], key=lambda s: s.strip().lower()
    )
    records = _dedup_preserve(
        [*prior.records, *new.records],
        key=lambda r: (r.subject, r.metric, r.unit, r.ts, r.value),
    )
    # files_touched: newest action for a path wins (new overrides prior).
    files_by_path: dict[str, Any] = {}
    for f in [*prior.files_touched, *new.files_touched]:
        files_by_path[f.path] = f

    return SessionExtraction(
        session_id=session_id,
        project_path=prior.project_path or new.project_path,
        branch=prior.branch or new.branch,
        started_at=prior.started_at or new.started_at,
        ended_at=new.ended_at or prior.ended_at,
        summary=merged_summary or new.summary or prior.summary,
        open_threads=open_threads,
        decisions=decisions,
        files_touched=list(files_by_path.values()),
        tools_used=tools_used,
        triplets=triplets,
        records=records,
    )


async def _generate(summarizer: Summarizer, prompt: str) -> str | None:
    """Call ``generate`` with one transient-error retry. None ⇒ both failed."""
    for attempt in (1, 2):
        try:
            text, usage = await _generate_with_usage(summarizer, prompt)
            return text
        except Exception as exc:  # noqa: BLE001 — transient provider error
            logger.warning("summarizer.generate failed (attempt %d): %s", attempt, exc)
    return None


async def _generate_with_usage(summarizer: Summarizer, prompt: str) -> tuple[str, Any]:
    """Call ``generate_with_usage`` if available, else fall back to generate().

    Records provider usage (channel="provider", source="session"). Best-effort —
    never breaks the caller.
    """
    from brainpalace_server.services.usage_metrics import record_usage  # noqa: PLC0415

    gw = getattr(summarizer, "generate_with_usage", None)
    if gw is not None:
        text, usage = await gw(prompt)
    else:
        from brainpalace_server.providers.base import Usage  # noqa: PLC0415

        text = await summarizer.generate(prompt)
        usage = Usage()

    try:
        record_usage(
            "provider",
            getattr(summarizer, "provider_name", ""),
            getattr(summarizer, "model_name", ""),
            "session",
            calls=1,
            tokens_in=getattr(usage, "tokens_in", 0),
            tokens_out=getattr(usage, "tokens_out", 0),
            cache_read=getattr(usage, "cache_read", 0),
            cache_write=getattr(usage, "cache_write", 0),
        )
    except Exception:  # noqa: BLE001 — telemetry must never break the caller
        pass
    return text, usage


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
    max_chunks: int = 0,
) -> SessionExtraction | None:
    """Single-pass for small transcripts; chunk + hierarchical merge for big.

    ``max_chunks`` (> 0, billable only — Task 4b) caps the number of per-part LLM
    calls: a giant transcript is truncated to the first ``max_chunks`` parts
    (logged) so one session cannot run an unbounded number of paid calls.
    """
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
    if max_chunks > 0 and len(parts) > max_chunks:
        logger.warning(
            "session %s: %d chunks exceeds provider_session_max_chunks=%d — "
            "truncating to the first %d (later turns dropped this pass)",
            session_id,
            len(parts),
            max_chunks,
            max_chunks,
        )
        parts = parts[:max_chunks]
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


def select_new_turns(turns: list[Turn], prior_offset: int) -> list[Turn]:
    """Turns newer than ``prior_offset`` that are safe to distil.

    ``Turn.index`` is the record's own identity (a positional counter for
    Claude Code, the transcript's ``step_index`` for tools that publish one),
    so this slice stays correct even when a tool REGENERATES its transcript
    rather than appending to it. Non-terminal turns are excluded: their content
    can still change, and distilling them now would either duplicate work or
    bake in a half-finished record.
    """
    return [t for t in turns if t.index > prior_offset and t.terminal]


def resume_offset_for(turns: list[Turn]) -> int:
    """Durable high-water mark to persist in the resume sidecar.

    The highest terminal index BELOW the first still-in-flight record — never
    the last position. An in-flight record must not be advanced past, whether
    it trails the transcript or sits in the MIDDLE (antigravity statuses mutate
    in place, so a RUNNING step can be followed by DONE ones): once the offset
    moves beyond it, its finished form would be skipped forever. Terminal turns
    after a gap may be re-selected on a later sweep — that is the safe
    direction (``merge_extractions`` is a structural union), while a skipped
    step is silent data loss.
    """
    non_terminal = [t.index for t in turns if not t.terminal]
    if not non_terminal:
        return max((t.index for t in turns), default=-1)
    gate = min(non_terminal)
    below = [t.index for t in turns if t.terminal and t.index < gate]
    return max(below) if below else -1


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
    record_store: Any | None = None,
    max_chunks: int = 0,
) -> SessionExtractResult | None:
    """Distil one transcript → store → mark. Returns the store result or None.

    Never raises: any failure (provider down, malformed output, oversized merge
    failure) returns ``None`` and leaves the session **un-marked** so the
    catch-up sweep retries it. A success writes the ``.done`` marker last.
    """
    meta, turns = parse_transcript(path)
    sid = _session_id(meta, path)

    # Serialize the read-modify-write per session (2b-3): an overlapping run waits
    # here, then re-reads the now-advanced offset below and no-ops on the delta.
    async with _distill_lock(project_root, sid):
        prior = read_progress(project_root, sid)
        if prior is not None:
            prior_offset, prior_extraction = prior
            # Append-only assumption (2b-5): Turn.index is positional in file order,
            # so this delta is correct only while transcripts are append-only (the
            # case for Claude Code). Documented at load_session's index counter.
            new_turns = select_new_turns(turns, prior_offset)
            if not new_turns:
                return None  # already current — nothing new to distil
            text = render_turns(new_turns)
            if not text.strip():
                return None
            new_payload = await _run_extraction(
                summarizer, text, meta, sid, chunk_chars, max_chunks
            )
            if new_payload is None:
                return None  # provider failed → leave for retry
            # Structural, no-LLM merge (2b-2) — lossless union, no re-summarization.
            payload = merge_extractions(prior_extraction, new_payload, sid)
        else:
            text = render_turns(select_new_turns(turns, -1))
            if not text.strip():
                if turns:
                    # Content exists but is all still in flight — do NOT mark;
                    # a later sweep picks it up once the steps settle.
                    return None
                # Truly empty transcript — mark so it is not reprocessed forever.
                write_marker(project_root, sid)
                return None
            fresh = await _run_extraction(
                summarizer, text, meta, sid, chunk_chars, max_chunks
            )
            if fresh is None:
                return None  # unmarked → retried by catch-up
            payload = fresh

        try:
            result = await SessionExtractService().store(
                payload,
                embedder=embedder,
                storage_backend=storage_backend,
                graph_store=graph_store,
                digest_path=digest_path,
                memory_service=memory_service,
                project_root=project_root,
                record_store=record_store,
            )
        except Exception as exc:  # noqa: BLE001 — never propagate into the watcher
            logger.warning("distill failed for %s: %s", path, exc)
            return None

        write_marker(project_root, sid)
        last_offset = resume_offset_for(turns)
        write_progress(project_root, sid, last_offset, payload)
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
        record_store: Any | None = None,
        max_chunks: int = 0,
        server_start_ts: float = 0.0,
        first_request_seen: Callable[[], bool] | None = None,
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
        self.record_store = record_store
        # Task 4b: per-session paid-call cap (billable only; 0 = unlimited).
        self.max_chunks = max_chunks
        # Task 4f: auto-grace anchored on subagent activity + cold-start gate
        # (replaces the mtime-age check in the auto path). first_request_seen is
        # read live (callable over app.state) so the gate opens on the first req.
        self._server_start_ts = server_start_ts
        self._first_request_seen = first_request_seen or (lambda: False)

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
        meta, _turns = parse_transcript(path)
        sid = _session_id(meta, path)
        if self.mode == "auto" and self._plugin_present():
            # Plugin owns extraction (subagent). Defer — UNLESS the provider is
            # auto-eligible: the subagent has been absent for a whole grace window
            # (anchored on last-drain + server_start, gated on first request),
            # i.e. a disabled/never-reopened plugin safety net (Task 4f — replaces
            # the per-session mtime-age check). Idempotent + unified marker =>
            # no double-run.
            if is_marked(self.project_root, sid):
                return None
            if not provider_auto_eligible(
                now=time.time(),
                last_drain_ts=read_last_drain(self.project_root),
                server_start_ts=self._server_start_ts,
                first_request_seen=self._first_request_seen(),
                grace_seconds=self.grace_seconds,
            ):
                return None  # fresh / cold-start — let the subagent handle it
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
                record_store=self.record_store,
                max_chunks=self.max_chunks,
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

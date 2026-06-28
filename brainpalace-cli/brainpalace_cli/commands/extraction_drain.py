"""Unified per-prompt drain over ``/extraction/pending?source=all``.

The Claude Code plugin's UserPromptSubmit hook calls :func:`unified_drain` once
per prompt. It fetches one bounded batch of pending extraction items (docs +
sessions), throttles them per source, and — on a non-empty selection — emits a
single **ids-only** directive routing doc ids to ONE ``graph-triplet-extractor``
dispatch and session ids to one ``chat-session-extractor`` each.

**Security invariant (H1, load-bearing — do NOT weaken):** the directive carries
**ids only, never chunk text**. The doc text is untrusted indexed content; it
must never reach the main model's context. Each agent fetches its own content by
id through the extraction MCP tools (``extraction_fetch``). The pending payload
*does* include ``text`` for the byte-size accounting on the server side, but this
module reads only ``id``/``path`` from doc/session items and never the ``text``.

Throttling:

- **doc count cap** (``doc_cap``): first ``doc_cap`` doc ids per turn (one
  batched dispatch). ``0`` = unlimited.
- **session byte budget + count cap** (``session_budget``/``session_cap``):
  greedy FIFO under the budget, first-pick-always so a single oversized session
  drains alone (see :func:`select_batch`).
- **cooldown-on-emit** (``cooldown``, E3): ``.brainpalace/last-drain`` is stamped
  only when a non-empty batch is emitted, then re-checked next turn; at most one
  batch per ``cooldown`` window. ``0`` drains every eligible prompt.

Fail-open (H3): any error fetching the pending batch → ``directive=None`` (the
hook injects nothing and never blocks).
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..client import DocServeClient

#: Unresolvable transcript → treat as infinitely large so it drains ALONE
#: (first-pick-always) rather than being silently grouped/dropped.
_LARGE = math.inf

#: Hot-path fetch timeout — a slow/starting server must never stall a prompt.
_FETCH_TIMEOUT = 1.0
#: Bounded pending batch (server clamps to its own max; keep small for the turn).
_FETCH_LIMIT = 20

DEFAULT_BUDGET_BYTES = 1_048_576  # 1 MB
DEFAULT_COOLDOWN_SECONDS = 300  # 5 min
DEFAULT_DOC_CAP = 4
DEFAULT_SESSION_CAP = 2


# --- config knob resolution (relocated from session_drain, reading `extraction:`) --


def _extract_block(project_root: Path) -> dict[str, Any]:
    """The project's ``extraction:`` mapping (empty on any problem)."""
    config_path = project_root / ".brainpalace" / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return {}
    block = data.get("extraction") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def _knob_int(env: str, cfg_key: str, project_root: Path, default: int) -> int:
    """Resolve an int knob: env → project ``extraction:`` config → default.

    Non-negative. Mirrors the precedence of the legacy session_drain resolvers,
    but reads the unified ``extraction:`` block.
    """
    raw = os.getenv(env)
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    val = _extract_block(project_root).get(cfg_key)
    if isinstance(val, bool):  # guard: YAML true/false is not a numeric knob
        return default
    if isinstance(val, int):
        return max(0, val)
    return default


def resolve_budget(project_root: Path) -> int:
    return _knob_int(
        "SESSION_DRAIN_BUDGET_BYTES",
        "drain_budget_bytes",
        project_root,
        DEFAULT_BUDGET_BYTES,
    )


def resolve_cooldown(project_root: Path) -> int:
    return _knob_int(
        "EXTRACTION_DRAIN_COOLDOWN_SECONDS",
        "drain_cooldown_seconds",
        project_root,
        DEFAULT_COOLDOWN_SECONDS,
    )


def resolve_doc_cap(project_root: Path) -> int:
    return _knob_int(
        "EXTRACTION_DRAIN_DOC_MAX_PER_TURN",
        "drain_doc_max_per_turn",
        project_root,
        DEFAULT_DOC_CAP,
    )


def resolve_session_cap(project_root: Path) -> int:
    return _knob_int(
        "EXTRACTION_DRAIN_SESSION_MAX_PER_TURN",
        "drain_session_max_per_turn",
        project_root,
        DEFAULT_SESSION_CAP,
    )


def resolve_max_pending(project_root: Path) -> int:
    return _knob_int(
        "EXTRACTION_MAX_PENDING",
        "max_pending",
        project_root,
        0,
    )


# --- byte-budget batch selection (relocated from session_drain) -------------


def select_batch(
    ids: list[str],
    size_of: Callable[[str], float],
    budget: int,
    cap: int,
) -> tuple[list[str], list[str]]:
    """Greedy FIFO batch under ``budget`` bytes and ``cap`` count.

    The first id is always taken (budget/cap checked only once a batch exists),
    so a single oversized session drains alone instead of stalling the queue.
    ``cap == 0`` means unlimited count. Returns ``(batch, remainder)``.
    """
    batch: list[str] = []
    total = 0.0
    for sid in ids:
        sz = size_of(sid)
        if batch and ((cap and len(batch) >= cap) or total + sz > budget):
            break
        batch.append(sid)
        total += sz
    return batch, ids[len(batch) :]


# --- pending fetch (errors propagate to unified_drain's fail-open guard) -----


def _fetch_pending(url: str, timeout: float) -> dict[str, Any]:
    """Fetch one bounded ``source=all`` pending batch. Errors propagate.

    The caller (:func:`unified_drain`) wraps this in a try/except so any failure
    fails open (no directive). Returns the server payload
    ``{"items": [...], "doc_pending_total": int}``.
    """
    with DocServeClient(base_url=url, timeout=timeout) as client:
        return client.get_extraction_pending(_FETCH_LIMIT, source="all")


# --- directive builder -------------------------------------------------------


def _build_directive(
    doc_ids: list[str],
    session_ids: list[str],
    *,
    doc_pending_total: int,
    max_pending: int,
) -> str:
    """Grouped, ids-only directive. NEVER includes any chunk ``text`` (H1)."""
    lines = [
        "Pending extraction (best-effort):",
        f"- doc chunks {doc_ids} → ONE graph-triplet-extractor "
        "(process all listed ids)",
        f"- sessions  {session_ids}      → one chat-session-extractor PER session",
        "Each agent fetches its own content via the extraction tools.",
    ]
    if max_pending > 0 and doc_pending_total >= max_pending:
        lines.append(
            f"Note: indexing is paused — {doc_pending_total} chunks queued "
            "(≥ max_pending). Likely an over-broad index; check exclude "
            "patterns or extraction.mode. Indexing resumes as the queue drains."
        )
    return "\n".join(lines)


def unified_drain(
    project_root: Path,
    *,
    url: str,
    doc_cap: int,
    session_budget: int,
    session_cap: int,
    cooldown: int,
    max_pending: int = 0,
    now: float | None = None,
) -> dict[str, Any]:
    """Drain one throttled batch over ``source=all``; build the ids-only directive.

    Returns ``{"directive": str|None, "doc_ids": [...], "session_ids": [...]}``.
    ``directive`` is ``None`` on an active cooldown, an empty batch, or any fetch
    error (fail-open). On a non-empty emit, ``.brainpalace/last-drain`` is stamped
    BEFORE the directive is built (cooldown-on-emit, E3).
    """
    import time as _time

    now = _time.time() if now is None else now
    # Server reads this from the grouped state/ subfolder
    # (storage_paths.state_file_path); keep the writer in lock-step.
    state = project_root / ".brainpalace" / "state"
    state.mkdir(parents=True, exist_ok=True)
    last = state / "last-drain"

    empty: dict[str, Any] = {"directive": None, "doc_ids": [], "session_ids": []}

    # Cooldown gate — at most one batch per window.
    if cooldown > 0 and last.exists():
        try:
            last_epoch = float(last.read_text().strip() or "0")
        except (OSError, ValueError):
            last_epoch = 0.0
        if now - last_epoch < cooldown:
            return empty

    # Fail-open: any fetch error → no directive.
    try:
        payload = _fetch_pending(url, _FETCH_TIMEOUT)
    except Exception:  # noqa: BLE001 — H3 fail-open: never block the prompt.
        return empty

    items = payload.get("items") or []
    doc_pending_total = int(payload.get("doc_pending_total", 0) or 0)

    # Split by source. Read ONLY id/path — never `text` (H1).
    doc_ids: list[str] = []
    session_ids: list[str] = []
    session_path: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        src = item.get("source")
        iid = item.get("id")
        if not iid:
            continue
        if src == "doc":
            doc_ids.append(str(iid))
        elif src == "session":
            session_ids.append(str(iid))
            session_path[str(iid)] = str(item.get("path") or "")

    # Docs: first `doc_cap` ids (0 = unlimited), one batched dispatch.
    if doc_cap:
        doc_ids = doc_ids[:doc_cap]

    # Sessions: byte-budget + count cap, first-pick-always.
    def size_of(sid: str) -> float:
        p = session_path.get(sid) or ""
        try:
            return float(Path(p).stat().st_size)
        except OSError:
            return _LARGE

    session_ids, _rest = select_batch(session_ids, size_of, session_budget, session_cap)

    if not doc_ids and not session_ids:
        return empty

    # Cooldown-on-emit (E3): stamp BEFORE building the directive.
    state.mkdir(parents=True, exist_ok=True)
    last.write_text(str(now), encoding="utf-8")

    directive = _build_directive(
        doc_ids,
        session_ids,
        doc_pending_total=doc_pending_total,
        max_pending=max_pending,
    )
    return {"directive": directive, "doc_ids": doc_ids, "session_ids": session_ids}

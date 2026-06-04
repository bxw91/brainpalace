"""`drain-queue` — size-throttled, cooldown-paced drain of the summarization gap.

The Claude Code plugin's UserPromptSubmit hook calls this once per prompt. It
drains a **bounded batch** of sessions that still need (re-)summarizing —
sourced from the **archive gap** (``pending_sessions``: quiescent archived
transcripts that are new, resumed-and-grown, or unmarked), not a queue file —
and hands them to the in-session model (which runs the free Haiku
``chat-session-extractor`` subagent on each).

Throttling (so a big backlog never clogs one interactive turn):

- **byte budget** (``drain_budget_bytes``, default 1 MB): take queued ids
  FIFO, summing each transcript's raw file size, until the next would exceed the
  budget.
- **count cap** (``drain_max_count``, default 8): secondary guard so many tiny
  sessions can't slip under the byte budget en masse.
- **first-pick-always (no starvation):** the first queued id is taken *before*
  the budget check, so a single oversized session drains **alone** rather than
  stalling the queue forever. There is no upper "too big, skip" ceiling — the
  extractor chunks oversized transcripts safely.
- **cooldown** (``drain_cooldown_seconds``, default 300): at most one batch per
  5-minute window (persisted in ``.brainpalace/last-drain``), so rapid-fire
  prompts don't trigger repeated drains. Backlog trickles out over active
  working time + across sessions. Set ``0`` to drain every eligible prompt.

Knob precedence: CLI flag → env var → project ``session_extraction:`` config →
default.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
import yaml

from ..discovery import discover_project_dir

#: Unresolvable transcript → treat as infinitely large so it drains ALONE
#: (first-pick-always) rather than being silently grouped/dropped.
_LARGE = math.inf

DEFAULT_BUDGET_BYTES = 1_048_576  # 1 MB
DEFAULT_MAX_COUNT = 8
DEFAULT_COOLDOWN_SECONDS = 300  # 5 min
DEFAULT_QUIESCENCE_SECONDS = 1800  # 30 min idle before summarizable


def _extract_block(project_root: Path) -> dict[str, Any]:
    """The project's ``session_extraction:`` mapping (empty on any problem)."""
    config_path = project_root / ".brainpalace" / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return {}
    block = data.get("session_extraction") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def _knob_int(env: str, cfg_key: str, project_root: Path, default: int) -> int:
    """Resolve an int knob: env → project config → default. Non-negative."""
    raw = os.getenv(env)
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    val = _extract_block(project_root).get(cfg_key)
    if isinstance(val, bool):  # guard: YAML true/false is not a byte count
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


def resolve_max_count(project_root: Path) -> int:
    return _knob_int(
        "SESSION_DRAIN_MAX_COUNT", "drain_max_count", project_root, DEFAULT_MAX_COUNT
    )


def resolve_cooldown(project_root: Path) -> int:
    return _knob_int(
        "SESSION_DRAIN_COOLDOWN_SECONDS",
        "drain_cooldown_seconds",
        project_root,
        DEFAULT_COOLDOWN_SECONDS,
    )


def resolve_quiescence(project_root: Path) -> int:
    return _knob_int(
        "SESSION_QUIESCENCE_SECONDS",
        "quiescence_seconds",
        project_root,
        DEFAULT_QUIESCENCE_SECONDS,
    )


def resolve_transcript_size(sid: str, sessions_dir: Path, archive_dir: Path) -> float:
    """Raw ``.jsonl`` byte size for a session id; ``inf`` if unresolvable.

    Looks in the live Claude Code transcript dir first, then recursively in the
    project's session archive. Unresolvable ⇒ ``inf`` (drains alone, never lost).
    """
    live = sessions_dir / f"{sid}.jsonl"
    if live.is_file():
        try:
            return float(live.stat().st_size)
        except OSError:
            return _LARGE
    if archive_dir.is_dir():
        for match in archive_dir.rglob(f"{sid}.jsonl"):
            if match.is_file():
                try:
                    return float(match.stat().st_size)
                except OSError:
                    return _LARGE
    return _LARGE


def select_batch(
    ids: list[str],
    size_of: Callable[[str], float],
    budget: int,
    cap: int,
) -> tuple[list[str], list[str]]:
    """Greedy FIFO batch under ``budget`` bytes and ``cap`` count.

    The first id is always taken (budget/cap checked only once a batch exists),
    so a single oversized session drains alone instead of stalling the queue.
    Returns ``(batch, remainder)``.
    """
    batch: list[str] = []
    total = 0.0
    for sid in ids:
        sz = size_of(sid)
        if batch and (len(batch) >= cap or total + sz > budget):
            break
        batch.append(sid)
        total += sz
    return batch, ids[len(batch) :]


def pending_ids(project_root: Path, now: float | None = None) -> list[tuple[str, str]]:
    """Sessions needing (re-)summarization, from the archive gap selector.

    Returns ``(session_id, archive_path)`` FIFO. Falls back to an empty list if
    the bundled server isn't importable (e.g. archive disabled)."""
    try:
        from brainpalace_server.services.session_distill_service import pending_sessions
    except Exception:  # noqa: BLE001 — server unavailable ⇒ nothing to drain here
        return []
    archive_dir = project_root / ".brainpalace" / "session_archive"
    idle = resolve_quiescence(project_root)
    result: list[tuple[str, str]] = pending_sessions(
        project_root, archive_dir, now=now, idle_seconds=idle
    )
    return result


def drain_queue(
    project_root: Path,
    *,
    budget: int,
    cap: int,
    cooldown: int,
    now: float | None = None,
) -> dict[str, Any]:
    """Drain one throttled batch from the archive gap. Returns a summary dict.

    ``{"drained": [ids], "remaining": int, "cooldown_active": bool}``. On an
    active cooldown (or no pending sessions) ``drained`` is empty. The gap is
    recomputed every run (archive ∖ fresh ``.done`` markers) — there is no queue
    file to rewrite.
    """
    import time as _time

    now = _time.time() if now is None else now
    state = project_root / ".brainpalace"
    last = state / "last-drain"

    pending = pending_ids(project_root, now=now)
    if not pending:
        return {"drained": [], "remaining": 0, "cooldown_active": False}

    if cooldown > 0 and last.exists():
        try:
            last_epoch = float(last.read_text().strip() or "0")
        except (OSError, ValueError):
            last_epoch = 0.0
        if now - last_epoch < cooldown:
            return {"drained": [], "remaining": len(pending), "cooldown_active": True}

    ids = [sid for sid, _ap in pending]
    path_of = dict(pending)

    def size_of(sid: str) -> float:
        try:
            return float(Path(path_of[sid]).stat().st_size)
        except OSError:
            return _LARGE

    batch, rest = select_batch(ids, size_of, budget, cap)
    state.mkdir(parents=True, exist_ok=True)
    last.write_text(str(now), encoding="utf-8")
    return {"drained": batch, "remaining": len(rest), "cooldown_active": False}


@click.command("drain-queue")
@click.option(
    "--project",
    "-p",
    type=click.Path(file_okay=False),
    default=None,
    help="Project root (default: discover .brainpalace/ from cwd).",
)
@click.option("--budget-bytes", type=int, default=None, help="Per-drain byte budget.")
@click.option(
    "--max-count", "max_count_opt", type=int, default=None, help="Per-drain count cap."
)
@click.option(
    "--cooldown-seconds", type=int, default=None, help="Min seconds between drains."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def drain_queue_command(
    project: str | None,
    budget_bytes: int | None,
    max_count_opt: int | None,
    cooldown_seconds: int | None,
    json_output: bool,
) -> None:
    """Drain a size-throttled, cooldown-paced batch from the extraction queue.

    Intended for the Claude Code plugin's UserPromptSubmit hook; safe to run by
    hand. Prints the drained session-ids (JSON: ``drained``/``remaining``/
    ``cooldown_active``)."""
    root = Path(project).resolve() if project else discover_project_dir(Path.cwd())
    if root is None:
        if json_output:
            click.echo(
                json.dumps({"drained": [], "remaining": 0, "cooldown_active": False})
            )
        return
    b = budget_bytes if budget_bytes is not None else resolve_budget(root)
    c = max_count_opt if max_count_opt is not None else resolve_max_count(root)
    cd = cooldown_seconds if cooldown_seconds is not None else resolve_cooldown(root)
    res = drain_queue(root, budget=b, cap=c, cooldown=cd)
    if json_output:
        click.echo(json.dumps(res))
    elif res["drained"]:
        click.echo(" ".join(res["drained"]))

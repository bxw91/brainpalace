"""Task 4f — auto-grace eligibility for the paid provider drain.

In ``auto`` mode the free subagent gets first dibs; the paid provider only mops
up when the subagent has been absent for a whole grace window. The old anchor was
each chunk's ``created_at`` / transcript ``mtime`` — the *wrong* anchor (fires on
artifact age regardless of whether Claude Code is active, and an idle server would
provider-drain on its first tick, billing before anyone opens Claude Code).

The shared eligibility check anchors instead on **subagent activity**:

    baseline = max(last_drain_ts, server_start_ts)
    eligible = first_request_seen AND (now - baseline) >= grace_seconds

- ``last_drain_ts`` (the hook's ``.brainpalace/last-drain`` stamp) defers the
  provider whenever the subagent drained recently — the free path stays in front.
- ``server_start_ts`` gives a fresh grace window after every restart (an idle
  server won't immediately bill; CC gets a full window to show up).
- ``first_request_seen`` is the cold-start gate: nothing auto-drains on the
  startup tick, only after the system is live and the mechanic self-selects
  CC-vs-non-CC first interactions.
"""

from __future__ import annotations

import logging
from pathlib import Path

from brainpalace_server.storage_paths import STATE_SUBDIR

logger = logging.getLogger(__name__)


def provider_auto_eligible(
    *,
    now: float,
    last_drain_ts: float | None,
    server_start_ts: float,
    first_request_seen: bool,
    grace_seconds: float,
) -> bool:
    """True when the paid provider may auto-drain (auto mode only)."""
    if not first_request_seen:
        return False
    baseline = max(last_drain_ts or 0.0, server_start_ts)
    return (now - baseline) >= grace_seconds


def read_last_drain(project_root: str | Path) -> float | None:
    """Read the subagent's last-drain epoch from ``.brainpalace/last-drain``.

    Returns ``None`` when the file is absent or unparseable (the hook has never
    stamped a drain, or the stamp is corrupt) — the caller treats that as "no
    recent subagent activity" so grace is anchored on ``server_start_ts``.
    """
    # Pure read — must not create directories as a side effect.
    p = Path(project_root) / ".brainpalace" / STATE_SUBDIR / "last-drain"
    try:
        return float(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None

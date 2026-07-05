"""Write-time salience scoring seam (Phase 5).

Shaped like the confidence validator registry (record_validation.py): a list of
scorers, aggregated by max, seeded with a default age-decay scorer. The salience
*model* is product work (P1.2); this ships only the seam + default.

Scorers receive the full Record (not RecordCandidate) so a product scorer can
key on domain/source — P1.2 salience is domain-aware (Finding B). All registry
state is guarded by a lock: the rule endpoint (FastAPI threadpool) and the
session-extraction pipeline both touch this module concurrently (Finding A).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from brainpalace_server.config.settings import settings
from brainpalace_server.models.record import Record

Scorer = Callable[[Record], float]
_SCORERS: list[Scorer] = []
_LOCK = threading.Lock()


def register_salience_scorer(fn: Scorer) -> None:
    """Product hook. A registered scorer participates in the max; it never edits
    engine source and never silently replaces the default."""
    with _LOCK:
        _SCORERS.append(fn)


def reset_salience_scorers() -> None:
    with _LOCK:
        _SCORERS.clear()
        _SCORERS.append(_age_decay)


def _half_life() -> float:
    half = getattr(settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 90.0)
    if isinstance(half, bool) or not isinstance(half, (int, float)) or half <= 0:
        return 0.0
    return float(half)


def _age_decay(rec: Record) -> float:
    """Seed scorer: 0.5 ** (age_days / half_life). Newer = higher. Missing or
    unparseable ts, or disabled half-life → 1.0 (no penalty). Mirrors the
    retrieval time-decay ranking (query_service._apply_time_decay)."""
    half = _half_life()
    if half <= 0 or not rec.ts:
        return 1.0
    try:
        d = datetime.fromisoformat(str(rec.ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return 1.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (datetime.now(timezone.utc) - d).total_seconds() / 86400.0)
    return float(0.5 ** (age_days / half))


_SCORERS.append(_age_decay)


def score_salience(rec: Record) -> float:
    with _LOCK:
        scorers = list(_SCORERS)  # snapshot; iterate outside the lock
    return max((s(rec) for s in scorers), default=1.0)

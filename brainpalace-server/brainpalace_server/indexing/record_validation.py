"""Confidence tiering = coverage check (C1) + the Phase-4 teaching seam."""

from __future__ import annotations

import math
import threading
from typing import Callable

from brainpalace_server.models.record import RecordCandidate

HIGH_CONFIDENCE = 1.0
PROVISIONAL_CONFIDENCE = 0.6
UNVERIFIED_CONFIDENCE = 0.3

Validator = Callable[[RecordCandidate], float]
_VALIDATORS: list[Validator] = []
_LOCK = threading.Lock()


def register_validator(fn: Validator) -> None:
    """Phase-4 product hook. Never edits engine source; a taught rule is gated
    by the user before it is registered (never silently activated)."""
    with _LOCK:
        _VALIDATORS.append(fn)


def reset_validators() -> None:
    with _LOCK:
        _VALIDATORS.clear()
        _VALIDATORS.extend([_authored, _numeric_sanity])


# authored, bounded — do NOT grow per user
_AUTHORED_CURRENCY_METRICS = {"amount"}
_AUTHORED_CURRENCY_UNITS = {"USD"}
# deterministic structural counts derived from the session extraction (Task 9)
_AUTHORED_COUNT_METRICS = {"files_touched", "tools_used", "decisions", "open_threads"}


def _authored(c: RecordCandidate) -> float:
    if c.metric in _AUTHORED_CURRENCY_METRICS and (
        c.unit is None or c.unit in _AUTHORED_CURRENCY_UNITS
    ):
        return HIGH_CONFIDENCE
    if c.metric in _AUTHORED_COUNT_METRICS and c.unit == "count":
        return HIGH_CONFIDENCE
    return 0.0


def _numeric_sanity(c: RecordCandidate) -> float:
    return PROVISIONAL_CONFIDENCE if math.isfinite(c.value) else 0.0


_VALIDATORS.extend([_authored, _numeric_sanity])


def score_confidence(c: RecordCandidate) -> float:
    with _LOCK:
        validators = list(_VALIDATORS)  # snapshot; iterate outside the lock
    best = max((v(c) for v in validators), default=0.0)
    return best if best > 0.0 else UNVERIFIED_CONFIDENCE

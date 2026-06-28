"""Task 4b — billable-only per-hour spend cap for the provider drain.

Spend caps are **billable-only** (spec "Resource guards & sizing"): a local /
keyless summarization provider (Ollama) has no dollar cost, so the per-hour
ceiling and per-session chunk cap are treated as unlimited there — only window-
chunking and the rate/cooldown apply. For a billable provider (cloud, API key
present) the rolling trailing-3600s counter bounds the absolute spend rate: at
the cap the reconciler tick stops and items stay pending for the next drain.
"""

from __future__ import annotations

from collections import deque
from typing import Any

#: Trailing window (seconds) the per-hour cap counts over.
_WINDOW_SECONDS = 3600.0


class ProviderBudget:
    """Rolling trailing-hour counter of paid provider calls.

    ``max_per_hour == 0`` ⇒ unlimited (``allow`` always True; ``record`` is a
    no-op accounting-wise). Otherwise ``allow(now)`` is True while fewer than
    ``max_per_hour`` calls fall inside the trailing ``_WINDOW_SECONDS`` ending at
    ``now``; ``record(now)`` appends a call timestamp.
    """

    def __init__(self, max_per_hour: int) -> None:
        self._max = max(0, int(max_per_hour))
        self._calls: deque[float] = deque()

    def _evict(self, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()

    def allow(self, now: float) -> bool:
        if self._max == 0:
            return True
        self._evict(now)
        return len(self._calls) < self._max

    def record(self, now: float) -> None:
        if self._max == 0:
            return  # unlimited — no need to track timestamps
        self._calls.append(now)


def is_billable(summarization_settings: Any) -> bool:
    """True when the summarization provider costs money (cloud + API key present).

    False for Ollama / any local provider and for a keyless cloud provider — no
    dollar cost, so the spend caps do not apply (window-chunking + rate still do).
    """
    if summarization_settings is None:
        return False
    provider = str(getattr(summarization_settings, "provider", "") or "").lower()
    if provider == "ollama":
        return False
    get_api_key = getattr(summarization_settings, "get_api_key", None)
    if not callable(get_api_key):
        return False
    try:
        return bool(get_api_key())
    except Exception:  # noqa: BLE001 — a key-resolution error ⇒ treat as not billable
        return False

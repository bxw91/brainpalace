"""Route set-level questions to compute; everything else to hybrid."""

from __future__ import annotations

_TELLS = (
    "how many",
    "number of",
    "count",
    "total",
    "sum",
    "average",
    "avg",
    "mean",
    "most",
    "highest",
    "least",
    "lowest",
    "maximum",
    "minimum",
    "fewest",
    "per week",
    "per month",
    "per day",
    "each week",
    "each month",
)


def classify_compute_intent(query: str) -> bool:
    """Return True when the query expresses a set-level aggregation intent.

    Uses a lightweight keyword tell-list — no LLM, deterministic.  False
    positives fall through to compute (which returns [] when no metric
    resolves) and the auto-router then falls back to hybrid, so precision
    failures are safe.
    """
    q = (query or "").lower()
    return any(t in q for t in _TELLS)

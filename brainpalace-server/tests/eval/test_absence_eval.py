"""Phase 3 Task 8 — router-growth eval: absence boundaries vs all modes.

Encodes the auto-route tie-break ORDER used by QueryService:
compute first, then scan, then absence, else hybrid. `expected_mode` is the
first classifier that fires in that order.
"""

from brainpalace_server.services.query_router import (
    classify_absence_intent,
    classify_compute_intent,
    classify_scan_intent,
)


def _route(q: str) -> str:
    if classify_compute_intent(q):
        return "compute"
    if classify_scan_intent(q):
        return "scan"
    if classify_absence_intent(q):
        return "absence"
    return "hybrid"


CASES = [
    # absence positives
    ("subjects with distance but not duration", "absence"),
    ("topics recorded in gmail but not session", "absence"),
    ("topics present in chat but absent from email", "absence"),
    ("gap between planned and shipped", "absence"),
    # compute wins when a metric-aggregation tell is present (order: compute first)
    ("how many files did I touch per week", "compute"),
    ("total sales per month", "compute"),
    # collision: a query carrying BOTH a compute tell and an absence tell routes
    # to compute (standing tie-break: metric-aggregation intent wins).
    ("how many subjects have distance but not duration", "compute"),
    # collision: scan tell "did i discuss" + absence tell "but not" on one query
    # -> scan wins per the standing tie-break (scan is tried before absence).
    ("what did I discuss in gmail but not session", "scan"),
    # scan owns utterance-history
    ("did i mention caching", "scan"),
    ("how often did I say refactor", "scan"),
    # plain retrieval
    ("how do I configure authentication", "hybrid"),
    ("what is reciprocal rank fusion", "hybrid"),
]


def test_router_growth_absence_boundaries() -> None:
    for q, expected in CASES:
        assert _route(q) == expected, q

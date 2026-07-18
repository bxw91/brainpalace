"""Phase 4 Task 8 — router-growth eval: timeline boundaries vs all modes.

Encodes the auto-route tie-break ORDER used by QueryService:
compute first, then scan, then absence, then timeline, then graph, else
hybrid. `expected_mode` is the first classifier that fires in that order.

L5: this asserts classifier tell-disjointness + order ONLY, not end-to-end
routing. At runtime an auto-route leg falls through on an EMPTY result
(query_service.py: `if compute_results:` …), so a case labelled `compute` here
may execute as hybrid when no record resolves. Do not read this as a runtime
routing proof — it guards that the tells don't overlap, same as the absence eval.
"""

from brainpalace_server.services.query_router import (
    classify_absence_intent,
    classify_compute_intent,
    classify_graph_intent,
    classify_scan_intent,
    classify_timeline_intent,
)


def _route(q: str) -> str:
    if classify_compute_intent(q):
        return "compute"
    if classify_scan_intent(q):
        return "scan"
    if classify_absence_intent(q):
        return "absence"
    if classify_timeline_intent(q):
        return "timeline"
    if classify_graph_intent(q):
        return "graph"
    return "hybrid"


CASES = [
    # timeline positives (temporal/evolution markers)
    ("how did the auth decision evolve", "timeline"),
    ("history of pyproject.toml", "timeline"),
    ("how has config.py changed over time", "timeline"),
    ("the retry policy used to be exponential", "timeline"),
    ("progression of the schema", "timeline"),
    # graph-relationship phrasing must NOT steal timeline — the timeline<->graph
    # boundary. It now routes to graph (D1) rather than falling through to
    # hybrid, since graph is a real auto-route leg.
    ("what depends on auth.py", "graph"),
    ("what relates to the cache module", "hybrid"),
    # graph positives (relationship-verb phrasing) must NOT steal timeline
    ("what calls auth.py", "graph"),
    ("who calls compile_scan", "graph"),
    ("classes that use AuthService", "graph"),
    # collision: compute tell + timeline tell -> compute wins (order)
    ("how many files changed over time", "compute"),
    # other modes still own their tells
    ("total sales per month", "compute"),
    ("did I mention caching", "scan"),
    ("subjects with distance but not duration", "absence"),
    # plain retrieval
    ("how do I configure authentication", "hybrid"),
    ("what is reciprocal rank fusion", "hybrid"),
]


def test_router_growth_timeline_boundaries() -> None:
    for q, expected in CASES:
        assert _route(q) == expected, q

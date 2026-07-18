"""Router-growth eval: graph boundaries vs all modes.

Encodes the auto-route tie-break ORDER used by QueryService: compute first,
then scan, then absence, then timeline, then graph (D2 — inserted last),
else hybrid. `expected_mode` is the first classifier that fires in that
order. Graph is the fifth classifier (D1); this suite asserts it does not
steal cases from compute/scan/absence/timeline, and is not stolen by them.
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
    # graph positives (relationship-verb phrasing)
    ("what calls auth.py", "graph"),
    ("what uses the cache module", "graph"),
    ("what imports query_router", "graph"),
    ("who calls compile_scan", "graph"),
    ("what depends on auth.py", "graph"),
    ("what references graph_store.py", "graph"),
    ("classes that use AuthService", "graph"),
    ("impact of changing the config schema", "graph"),
    # other modes still own their tells — graph must not steal them
    ("total sales per month", "compute"),
    ("did I mention caching", "scan"),
    ("subjects with distance but not duration", "absence"),
    ("how did the auth decision evolve", "timeline"),
    # collision: an earlier classifier's tell alongside a graph tell -> the
    # earlier classifier wins per the standing auto-route order
    ("how many modules depend on auth.py", "compute"),
    # plain retrieval — bare "how" must not fire graph
    ("how does the retriever work", "hybrid"),
    ("how do I configure authentication", "hybrid"),
    ("what is reciprocal rank fusion", "hybrid"),
]


def test_router_growth_graph_boundaries() -> None:
    for q, expected in CASES:
        assert _route(q) == expected, q

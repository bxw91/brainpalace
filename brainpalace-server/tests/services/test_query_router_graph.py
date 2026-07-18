"""Graph intent tells (disjoint from compute/scan/absence/timeline)."""

from brainpalace_server.services.query_router import (
    classify_absence_intent,
    classify_compute_intent,
    classify_graph_intent,
    classify_scan_intent,
    classify_timeline_intent,
)

POSITIVE = [
    "what calls auth.py",
    "what uses the cache module",
    "what imports query_router",
    "who calls compile_scan",
    "what depends on auth.py",
    "what references graph_store.py",
    "classes that use AuthService",
    "impact of changing the config schema",
]

NEGATIVE = [
    "how do I configure authentication",  # plain retrieval
    "how did the auth decision evolve",  # timeline
    "how many files did I touch per week",  # compute
    "did I mention the retry bug",  # scan
    "subjects with distance but not duration",  # absence
    "how does the retriever work",  # bare "how" must not fire
]


def test_positive_cases() -> None:
    for q in POSITIVE:
        assert classify_graph_intent(q), q


def test_negative_cases() -> None:
    for q in NEGATIVE:
        assert not classify_graph_intent(q), q


def test_disjoint_from_other_classifiers() -> None:
    q = "what depends on auth.py"
    assert classify_graph_intent(q)
    assert not classify_compute_intent(q)
    assert not classify_scan_intent(q)
    assert not classify_absence_intent(q)
    assert not classify_timeline_intent(q)

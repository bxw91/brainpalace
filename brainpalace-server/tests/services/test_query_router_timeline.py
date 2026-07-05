"""Phase 4 Task 4 — timeline intent tells (disjoint from compute/scan/absence)."""

from brainpalace_server.services.query_router import (
    classify_absence_intent,
    classify_compute_intent,
    classify_scan_intent,
    classify_timeline_intent,
)

POSITIVE = [
    "how did the auth decision evolve",
    "history of auth.py",
    "how has config.py changed over time",
    "the retry policy used to be exponential",
    "evolution of the cache design",
    "progression of the schema",
]

NEGATIVE = [
    "how do I configure authentication",  # plain retrieval
    "what depends on auth.py",  # graph relationship phrasing
    "how many files did I touch per week",  # compute
    "did I mention the retry bug",  # scan
    "subjects with distance but not duration",  # absence
]


def test_positive_cases() -> None:
    for q in POSITIVE:
        assert classify_timeline_intent(q), q


def test_negative_cases() -> None:
    for q in NEGATIVE:
        assert not classify_timeline_intent(q), q


def test_disjoint_from_other_classifiers() -> None:
    q = "how did the auth decision evolve"
    assert classify_timeline_intent(q)
    assert not classify_compute_intent(q)
    assert not classify_scan_intent(q)
    assert not classify_absence_intent(q)

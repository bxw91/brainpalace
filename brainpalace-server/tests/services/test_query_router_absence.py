"""Phase 3 Task 4 — absence intent tells (disjoint from compute/scan)."""

from brainpalace_server.services.query_router import (
    classify_absence_intent,
    classify_compute_intent,
    classify_scan_intent,
)

POSITIVE = [
    "subjects with distance but not duration",
    "what did I discuss in gmail but not session",
    "topics present in chat but absent from email",
    "notes without a follow-up",
    "gap between planned and shipped",
]

NEGATIVE = [
    "how do I configure authentication",  # plain retrieval
    "how many files did I touch per week",  # compute
    "did I mention the retry bug",  # scan
    "total sales per month",  # compute
]


def test_positive_cases() -> None:
    for q in POSITIVE:
        assert classify_absence_intent(q), q


def test_negative_cases() -> None:
    for q in NEGATIVE:
        assert not classify_absence_intent(q), q


def test_disjoint_from_compute_and_scan() -> None:
    # absence tells do not fire compute/scan classifiers on the same query
    q = "subjects with distance but not duration"
    assert classify_absence_intent(q)
    assert not classify_compute_intent(q)
    assert not classify_scan_intent(q)

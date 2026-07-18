"""Phase 2 Task 5 — scan intent tells (multiword, precision-first)."""

from brainpalace_server.services.query_router import (
    classify_compute_intent,
    classify_scan_intent,
)

POSITIVE = [
    "which week did I mention foobar most",
    "how many times did I say refactor",
    "how often did I talk about caching",
    "did I mention the retry bug last month",
    "which month did we discuss the release",
]

NEGATIVE = [
    "how do I configure authentication",  # plain retrieval
    "how many files did I touch per week",  # compute, not scan
    "what is reciprocal rank fusion",  # plain retrieval
    "total sales per month",  # compute
]


def test_positive_cases() -> None:
    for q in POSITIVE:
        assert classify_scan_intent(q), q


def test_negative_cases() -> None:
    for q in NEGATIVE:
        assert not classify_scan_intent(q), q


def test_utterance_verb_excludes_compute() -> None:
    # 'how many times did I say X' carries a compute tell ("how many") but
    # also an utterance-verb phrase ("did i say"). _COMPUTE_ANTI_TELLS (D5)
    # excludes utterance-verb phrasing from compute outright, so scan owns
    # this query directly rather than via the auto-router's order tie-break.
    q = "how many times did I say refactor"
    assert classify_scan_intent(q)
    assert not classify_compute_intent(q)

"""Unit tests for the eval scorer. Pure functions — no network, no API key, so
this file runs in the normal pytest suite."""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.eval.scorer import (
    recall_at_k,
    reciprocal_rank,
    score_all,
    score_case,
)


@dataclass
class FakeCase:
    id: str
    mode: str
    k: int
    expected: list[str]
    retrieved: list[str] = field(default_factory=list)
    error: str | None = None


def test_recall_full_hit():
    assert recall_at_k(["a/auth.md", "b/rate.md"], ["auth.md"], k=3) == 1.0


def test_recall_partial():
    # one of two expected found within top-k
    r = recall_at_k(["x/auth.md", "y/other.md"], ["auth.md", "session.py"], k=3)
    assert r == 0.5


def test_recall_respects_k():
    # expected hit sits at rank 3 but k=2 → not counted
    assert recall_at_k(["a.md", "b.md", "z/auth.md"], ["auth.md"], k=2) == 0.0


def test_recall_no_expected_is_zero():
    assert recall_at_k(["a.md"], [], k=3) == 0.0


def test_reciprocal_rank_first_position():
    assert reciprocal_rank(["z/auth.md", "b.md"], ["auth.md"], k=3) == 1.0


def test_reciprocal_rank_third_position():
    rr = reciprocal_rank(["a.md", "b.md", "z/auth.md"], ["auth.md"], k=3)
    assert rr == 1.0 / 3


def test_reciprocal_rank_miss_is_zero():
    assert reciprocal_rank(["a.md", "b.md"], ["auth.md"], k=3) == 0.0


def test_reciprocal_rank_beyond_k_is_zero():
    assert reciprocal_rank(["a.md", "b.md", "z/auth.md"], ["auth.md"], k=2) == 0.0


def test_suffix_match_not_substring():
    # "auth.md" must match by path suffix, not appear mid-path
    assert recall_at_k(["x/auth.md.bak"], ["auth.md"], k=3) == 0.0


def test_score_case_errored_is_zero():
    c = FakeCase(
        id="e", mode="bm25", k=3, expected=["auth.md"], error="Boom: nope"
    )
    s = score_case(c)
    assert s.recall == 0.0 and s.rr == 0.0 and s.error == "Boom: nope"
    assert s.hit is False


def test_aggregate_overall_and_per_mode():
    cases = [
        FakeCase("a", "bm25", 3, ["auth.md"], ["z/auth.md"]),  # rr=1, recall=1
        FakeCase("b", "bm25", 3, ["x.md"], ["y.md", "n.md", "x.md"]),  # rr=1/3
        FakeCase("c", "hybrid", 3, ["s.py"], ["a.md"]),  # miss
    ]
    scores, summary = score_all(cases)
    assert summary["overall"]["cases"] == 3
    assert summary["by_mode"]["bm25"]["cases"] == 2
    assert summary["by_mode"]["bm25"]["recall_at_k"] == 1.0
    assert abs(summary["by_mode"]["bm25"]["mrr"] - (1.0 + 1.0 / 3) / 2) < 1e-9
    assert summary["by_mode"]["hybrid"]["mrr"] == 0.0


def test_mode_agreement_delta():
    cases = [
        FakeCase("a", "bm25", 3, ["x.md"], ["a.md", "b.md", "x.md"]),  # rr=1/3
        FakeCase("b", "hybrid", 3, ["x.md"], ["x.md"]),  # rr=1
    ]
    _, summary = score_all(cases)
    delta = summary["mode_agreement"]["hybrid_vs_bm25_mrr_delta"]
    assert abs(delta - (1.0 - 1.0 / 3)) < 1e-9


def test_aggregate_empty():
    scores, summary = score_all([])
    assert scores == []
    assert summary["overall"]["cases"] == 0
    assert summary["mode_agreement"]["hybrid_vs_bm25_mrr_delta"] is None

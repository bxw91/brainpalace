"""Rank-based scoring for the retrieval eval.

Pure functions, no I/O — unit-tested in ``test_scorer.py`` and safe to run in
the normal pytest suite (no network, no key). Metrics are rank-based over stable
source identifiers so they don't wobble with raw embedding scores:

- **recall@k** — fraction of a case's expected sources found in its top-k.
- **reciprocal rank** — ``1 / rank`` of the first expected hit (0 if none),
  whose mean over cases is the familiar MRR.
- **mode-agreement** — informational: did fusion (hybrid) actually beat the
  keyword (bm25) baseline on overlapping cases?

A retrieved source matches an expected entry when the retrieved path *ends with*
the expected suffix (so ``"auth.md"`` matches ``".../corpus/auth.md"``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _CaseLike(Protocol):
    id: str
    mode: str
    k: int
    expected: list[str]
    retrieved: list[str]
    error: str | None


def _matches(source: str, expected_suffix: str) -> bool:
    return source.endswith(expected_suffix)


def _first_hit_rank(retrieved: list[str], expected: list[str]) -> int | None:
    """1-based rank of the first retrieved source matching any expected suffix."""
    for rank, source in enumerate(retrieved, start=1):
        if any(_matches(source, exp) for exp in expected):
            return rank
    return None


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """Fraction of distinct expected suffixes hit within the top-k results."""
    if not expected:
        return 0.0
    topk = retrieved[:k]
    hits = sum(1 for exp in expected if any(_matches(s, exp) for s in topk))
    return hits / len(expected)


def reciprocal_rank(retrieved: list[str], expected: list[str], k: int) -> float:
    """1/rank of the first expected hit within top-k, else 0.0."""
    rank = _first_hit_rank(retrieved[:k], expected)
    return 1.0 / rank if rank is not None else 0.0


@dataclass
class CaseScore:
    id: str
    mode: str
    k: int
    expected: list[str]
    retrieved: list[str]
    recall: float
    rr: float
    error: str | None = None

    @property
    def hit(self) -> bool:
        return self.rr > 0.0


def score_case(case: _CaseLike) -> CaseScore:
    """Score a single case result. An errored case scores zero on every metric."""
    if case.error:
        return CaseScore(
            id=case.id,
            mode=case.mode,
            k=case.k,
            expected=list(case.expected),
            retrieved=list(case.retrieved),
            recall=0.0,
            rr=0.0,
            error=case.error,
        )
    return CaseScore(
        id=case.id,
        mode=case.mode,
        k=case.k,
        expected=list(case.expected),
        retrieved=list(case.retrieved),
        recall=recall_at_k(case.retrieved, case.expected, case.k),
        rr=reciprocal_rank(case.retrieved, case.expected, case.k),
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(scores: list[CaseScore]) -> dict[str, Any]:
    """Mean recall@k + MRR overall and per mode, plus mode-agreement note.

    Returns a JSON-serialisable dict:

        {
          "overall": {"cases": N, "errors": E, "recall_at_k": r, "mrr": m},
          "by_mode": {"bm25": {...}, "vector": {...}, "hybrid": {...}},
          "mode_agreement": {"hybrid_vs_bm25_mrr_delta": float | None},
        }
    """
    by_mode: dict[str, dict[str, float | int]] = {}
    modes = sorted({s.mode for s in scores})
    for mode in modes:
        mode_scores = [s for s in scores if s.mode == mode]
        by_mode[mode] = {
            "cases": len(mode_scores),
            "errors": sum(1 for s in mode_scores if s.error),
            "recall_at_k": _mean([s.recall for s in mode_scores]),
            "mrr": _mean([s.rr for s in mode_scores]),
        }

    overall = {
        "cases": len(scores),
        "errors": sum(1 for s in scores if s.error),
        "recall_at_k": _mean([s.recall for s in scores]),
        "mrr": _mean([s.rr for s in scores]),
    }

    # Informational: fusion should not do worse than raw keyword on these cases.
    hybrid_mrr = by_mode.get("hybrid", {}).get("mrr")
    bm25_mrr = by_mode.get("bm25", {}).get("mrr")
    delta = (
        float(hybrid_mrr) - float(bm25_mrr)
        if hybrid_mrr is not None and bm25_mrr is not None
        else None
    )

    return {
        "overall": overall,
        "by_mode": by_mode,
        "mode_agreement": {"hybrid_vs_bm25_mrr_delta": delta},
    }


def score_all(cases: list[_CaseLike]) -> tuple[list[CaseScore], dict[str, Any]]:
    """Score every case and return (per-case scores, aggregate summary)."""
    scores = [score_case(c) for c in cases]
    return scores, aggregate(scores)

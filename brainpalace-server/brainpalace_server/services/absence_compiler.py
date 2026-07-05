"""Deterministic NL -> absence-plan compiler (Phase 3, mirrors compute_compiler).

An absence plan names TWO partition values in the SAME indexed column
(metric|source|domain) split by a negation-of-counterpart token: subjects
present under ``present_in`` but absent under ``absent_from``. Values are
resolved from the store's live vocabulary only — a token that is not a stored
value never resolves, so free-text framings ("planned but never implemented")
return None and the caller falls back to hybrid.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from brainpalace_server.services.compute_compiler import _date_range

#: Negation-of-counterpart splits, tried in order (longest/most-specific first).
_SPLITS = (
    " but never ",
    " but not in ",
    " but not ",
    " missing from ",
    " absent from ",
    " without ",
    " not in ",
)


class AbsencePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    partition: str  # metric|source|domain
    present_in: str
    absent_from: str
    key: str = "subject"
    metric: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int | None = None


def _resolve(text: str, vocab: list[str]) -> str | None:
    # Word-boundary match (NOT raw substring) so a stored value like "weight"
    # never resolves from "weightlifting" and "note" never from "another".
    for v in sorted(vocab, key=len, reverse=True):  # longest match first
        if v and re.search(rf"\b{re.escape(v.lower())}\b", text):
            return v
    return None


def compile_absence(
    query: str,
    known_metrics: list[str],
    known_sources: list[str],
    known_domains: list[str],
) -> AbsencePlan | None:
    q = (query or "").lower()
    split = next((s for s in _SPLITS if s in q), None)
    if split is None:
        return None
    left, right = q.split(split, 1)
    # precedence: source (roadmap headline axis) > domain > metric
    for partition, vocab in (
        ("source", known_sources),
        ("domain", known_domains),
        ("metric", known_metrics),
    ):
        a = _resolve(left, vocab)
        b = _resolve(right, vocab)
        if a and b and a != b:
            metric = None
            if partition != "metric":
                metric = _resolve(q, known_metrics)
            since, until = _date_range(q)
            return AbsencePlan(
                partition=partition,
                present_in=a,
                absent_from=b,
                metric=metric,
                since=since,
                until=until,
            )
    return None

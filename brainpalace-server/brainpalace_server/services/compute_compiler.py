"""Deterministic NL -> set-operation compiler for the compute mode."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict


class ComputePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    metric: str
    op: str  # sum|count|avg|max|min
    group_by: str | None = None
    order: str = "desc"
    limit: int | None = None
    since: str | None = None
    until: str | None = None


_OP_TELLS = [
    (("how many", "number of", "count"), "count"),
    (("total", "sum", "altogether", "combined"), "sum"),
    (("average", "avg", "mean"), "avg"),
]
_DESC = ("most", "highest", "max", "maximum", "top", "largest")
_ASC = ("least", "lowest", "min", "minimum", "smallest", "fewest")
_GROUPS = ("week", "month", "source", "subject", "unit")


def _match_metric(
    q: str, known_metrics: list[str], known_subjects: list[str] | None = None
) -> str | None:
    # known_subjects reserved for future subject->metric mapping; unused today.
    for name in sorted(known_metrics, key=len, reverse=True):  # exact / plural
        n = name.lower()
        if n in q or (len(n) > 3 and n.rstrip("s") in q):
            return name
    toks = set(re.findall(r"[a-z_]+", q))  # token overlap
    for m in known_metrics:  # "files" -> "files_touched"
        if set(m.lower().split("_")) & toks:
            return m
    return None  # nothing resolves -> caller falls back to hybrid (no arbitrary guess)


_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}


def _date_range(q: str) -> tuple[str | None, str | None]:
    """Minimal 'in <month> <year>' -> ISO [since, until). A bare month with no
    year is ambiguous -> (None, None) = all-time (never guess the year)."""
    m = re.search(r"\b(" + "|".join(_MONTHS) + r")\b(?:\s+(\d{4}))?", q)
    if not m or not m.group(2):
        return None, None
    mon, year = _MONTHS[m.group(1)], int(m.group(2))
    ny, nm = (year + 1, 1) if mon == 12 else (year, mon + 1)
    return f"{year}-{mon:02d}-01T00:00:00", f"{ny}-{nm:02d}-01T00:00:00"


def compile_compute(
    query: str,
    known_metrics: list[str],
    known_subjects: list[str] | None = None,
) -> ComputePlan | None:
    q = (query or "").lower()
    op = next((o for tells, o in _OP_TELLS if any(t in q for t in tells)), None)
    asc = any(t in q for t in _ASC)
    desc = any(t in q for t in _DESC)
    superlative = asc or desc
    if op is None and not superlative:
        return None
    group_by = next(
        (
            g
            for g in _GROUPS
            if f"per {g}" in q or f"each {g}" in q or f"by {g}" in q or f" {g}" in q
        ),
        None,
    )
    metric = _match_metric(q, known_metrics, known_subjects)
    if metric is None:
        return None
    order = "asc" if asc else "desc"
    limit = 1 if (superlative and group_by and ("which" in q or "what" in q)) else None
    if op is None:
        op = "sum" if group_by else ("min" if asc else "max")
    since, until = _date_range(q)
    return ComputePlan(
        metric=metric,
        op=op,
        group_by=group_by,
        order=order,
        limit=limit,
        since=since,
        until=until,
    )

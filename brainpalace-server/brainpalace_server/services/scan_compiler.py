"""Deterministic NL -> scan-plan compiler (Phase 2, mirrors compute_compiler).

A scan plan names ONE term (word or quoted phrase) to count over the session
archive, optionally bucketed by week/month/day/source. No term resolves ->
None -> the caller falls back to normal retrieval (never guess a term).

The auto-router calls with ``explicit=False`` and keeps the strict "never
guess" contract. Explicit ``--mode scan`` calls with ``explicit=True``, which
adds one forgiving fallback: a bare single-token query (no quotes, no tell) is
taken as the term, so ``scan "profile"`` and ``scan profile`` behave the same.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from brainpalace_server.services.compute_compiler import _date_range


class ScanPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    term: str
    group_by: str | None = None  # week|month|day|source
    order: str = "desc"
    limit: int | None = None
    since: str | None = None
    until: str | None = None


_QUOTED = re.compile(r"['\"]([^'\"]{2,80})['\"]")
_TERM_AFTER = re.compile(
    r"\b(?:mention(?:ed)?|say|said|discuss(?:ed)?|talk(?:ed)?\s+about)\s+"
    r"(?:the\s+(?:word|term|phrase)\s+)?([A-Za-z0-9_][\w.\-]*)"
)
#: Captured words that are grammar, not terms — compile to None instead.
_STOP_TERMS = {
    "the",
    "a",
    "an",
    "it",
    "that",
    "this",
    "them",
    "most",
    "least",
    "in",
    "on",
    "at",
    "by",
    "about",
    "anything",
    "something",
    "word",
}
_GROUPS = ("week", "month", "day", "source")
_ASC = ("least", "fewest", "lowest")


def _extract_term(query: str, q: str, explicit: bool) -> str | None:
    m = _QUOTED.search(query)  # original casing irrelevant; analyzer lowercases
    if m:
        return m.group(1).strip()
    m = _TERM_AFTER.search(q)
    if m and m.group(1) not in _STOP_TERMS:
        return m.group(1)
    # Explicit `--mode scan`: a bare SINGLE-token query is unambiguous intent, so
    # count it as the term (as if quoted). Multi-word stays strict — with no
    # quotes/tell there is no way to tell which word to count. The auto-router
    # (explicit=False) never reaches here, so plain hybrid queries are unaffected.
    if explicit:
        stripped = (query or "").strip()
        if 2 <= len(stripped) <= 80 and not re.search(r"\s", stripped):
            return stripped
    return None


def compile_scan(query: str, *, explicit: bool = False) -> ScanPlan | None:
    q = (query or "").lower()
    term = _extract_term(query or "", q, explicit)
    if not term:
        return None
    group_by = next(
        (
            g
            for g in _GROUPS
            if f"per {g}" in q or f"each {g}" in q or f"which {g}" in q or f" {g}" in q
        ),
        None,
    )
    order = "asc" if any(t in q for t in _ASC) else "desc"
    limit = 1 if (group_by and ("which" in q or "what" in q)) else None
    since, until = _date_range(q)
    return ScanPlan(
        term=term,
        group_by=group_by,
        order=order,
        limit=limit,
        since=since,
        until=until,
    )

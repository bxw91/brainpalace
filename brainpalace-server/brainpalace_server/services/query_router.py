"""Route set-level questions to compute/scan/absence/timeline; else hybrid."""

from __future__ import annotations

_TELLS = (
    "how many",
    "number of",
    "count",
    "total",
    "sum",
    "average",
    "avg",
    "mean",
    "most",
    "highest",
    "least",
    "lowest",
    "maximum",
    "minimum",
    "fewest",
    "per week",
    "per month",
    "per day",
    "each week",
    "each month",
)


def classify_compute_intent(query: str) -> bool:
    """Return True when the query expresses a set-level aggregation intent.

    Uses a lightweight keyword tell-list — no LLM, deterministic.  False
    positives fall through to compute (which returns [] when no metric
    resolves) and the auto-router then falls back to hybrid, so precision
    failures are safe.
    """
    q = (query or "").lower()
    return any(t in q for t in _TELLS)


_SCAN_TELLS = (
    "did i mention",
    "did we mention",
    "did i say",
    "did we say",
    "did i talk about",
    "did we talk about",
    "did i discuss",
    "did we discuss",
    "how often did",
    "times did i",
    "times did we",
    "which week did",
    "which month did",
    "which day did",
    "mention the word",
    "say the word",
)


def classify_scan_intent(query: str) -> bool:
    """True when the query asks about the user's own past utterances.

    Multiword tells keep precision high; false positives are safe — scan
    returns [] when no term compiles or nothing matches, and the auto-router
    falls back to hybrid. The compute<->scan tie-break lives in the caller's
    ORDER (compute tried first): a typed record metric wins, else scan.
    """
    q = (query or "").lower()
    return any(t in q for t in _SCAN_TELLS)


_ABSENCE_TELLS = (
    "but not",
    "but never",
    "without",
    "missing from",
    "absent from",
    "present in",
    "not in",
    "gap between",
    "never mentioned",
)


def classify_absence_intent(query: str) -> bool:
    """True when the query asks for an anti-join (present under one partition,
    absent under another).

    Tell strings are distinct from compute/scan tells, but a query may carry
    both (e.g. "how many ... but not ..."); the auto-route order
    (compute -> scan -> absence) is the tie-break — metric-aggregation intent
    wins. False positives are safe — absence returns [] when no two partition
    values resolve or nothing qualifies, and the router falls back to hybrid.
    """
    q = (query or "").lower()
    return any(t in q for t in _ABSENCE_TELLS)


_TIMELINE_TELLS = (
    "evolve",
    "evolved",
    "evolution of",
    "used to",
    "over time",
    "history of",
    "timeline of",
    "timeline for",
    "progression of",
    "changed over",
    "change over",
    "before and after",
)


def classify_timeline_intent(query: str) -> bool:
    """True when the query asks how a belief/fact evolved over time.

    Tells require an explicit temporal/evolution marker (deliberately NOT bare
    "how did", which fires on plain retrieval) — disjoint from compute
    (aggregation), scan (utterance history), absence (anti-join), AND graph
    relationship phrasing ("what depends on / relates to X"). Graph mode is
    explicit-only, so there is no runtime timeline<->graph collision. False
    positives are safe — timeline returns [] when no entity resolves or the
    entity has no edges, and the auto-router falls back to hybrid. The auto-route
    order (compute -> scan -> absence -> timeline) is the tie-break when a query
    carries a compute tell too: metric-aggregation wins.
    """
    q = (query or "").lower()
    return any(t in q for t in _TIMELINE_TELLS)

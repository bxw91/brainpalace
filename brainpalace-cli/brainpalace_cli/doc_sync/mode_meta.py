# brainpalace-cli/brainpalace_cli/doc_sync/mode_meta.py
"""Single source of prose metadata for every query `--mode` value. Mode NAMES come
live from the `--mode` Choice (introspect.py `_extract_modes`) — this module only
supplies the human-authored description/best-for/example per mode. `resolve_meta`
is the gate: a live mode with no entry here raises loudly instead of silently
rendering a blank column, so a new mode can never ship undocumented in the 4
generated doc tables (README, USER_GUIDE, API_REFERENCE, plugin brainpalace-query.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModeMeta:
    description: str
    best_for: str
    example: str


MODE_META: dict[str, ModeMeta] = {
    "vector": ModeMeta(
        description="Semantic similarity search",
        best_for="Conceptual understanding",
        example="Explain the architecture",
    ),
    "bm25": ModeMeta(
        description="Keyword matching",
        best_for="Exact terms, error codes",
        example="NullPointerException, getUserById",
    ),
    "hybrid": ModeMeta(
        description="Vector + BM25 fusion (default)",
        best_for="General questions",
        example="How does caching work?",
    ),
    "graph": ModeMeta(
        description="Knowledge graph relationships (empty unless the graph is built)",
        best_for="Relationships, dependencies",
        example="What classes use AuthService?",
    ),
    "multi": ModeMeta(
        description="Fusion of vector + BM25 + graph via RRF",
        best_for="Comprehensive recall",
        example="Everything about data validation",
    ),
    "compute": ModeMeta(
        description="Set-level aggregation over typed numeric records",
        best_for=(
            "Aggregates over your sessions (sum/count/avg, by week/month, "
            "superlatives)"
        ),
        example="How many files did I touch this week?",
    ),
    "scan": ModeMeta(
        description=(
            "Deterministic term counts over archived session transcripts "
            "(empty when the session archive is off)"
        ),
        best_for="Utterance history over sessions",
        example="Which week did I mention retries most?",
    ),
    "absence": ModeMeta(
        description=(
            "Anti-join over typed records (empty when no two stored values resolve)"
        ),
        best_for="Subjects present under one value but absent under another",
        example="Subjects with distance but not duration",
    ),
    "timeline": ModeMeta(
        description=(
            "Edge-validity/supersession history walk (empty when the entity "
            "resolves to no graph node)"
        ),
        best_for="How a belief/fact evolved over time",
        example="How did the auth decision evolve?",
    ),
}


def resolve_meta(modes: list[str]) -> list[tuple[str, ModeMeta]]:
    """Return (mode, meta) pairs in the given order. Raises ValueError if any mode
    lacks a MODE_META entry — the gate that forces an author to add metadata here
    the moment a new mode ships (keeps MODE_META and the live Choice in sync)."""
    missing = [m for m in modes if m not in MODE_META]
    if missing:
        raise ValueError(
            f"MODE_META is missing entries for live mode(s): {missing!r}. "
            "Add a ModeMeta to brainpalace_cli.doc_sync.mode_meta.MODE_META "
            "for each before regenerating docs."
        )
    return [(m, MODE_META[m]) for m in modes]

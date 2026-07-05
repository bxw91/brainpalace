"""Deterministic NL -> timeline-plan compiler (Phase 4, mirrors absence_compiler).

A timeline plan names ONE entity whose edge-validity/supersession history is
walked. The query must carry an explicit temporal/evolution structure — a
"history/timeline/evolution/progression of X" phrase, a "how did X evolve/change"
phrase, or "X used to …". Plain retrieval ("how did I configure auth") and graph
relationship phrasing ("what depends on X") carry no such marker and return None,
so the caller falls back to hybrid. The entity is NOT resolved here (the node
namespace is unbounded); the executor resolves it via graph.search_nodes.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

#: Ordered, most-specific first. Group 1 is the raw entity phrase.
_ENTITY_PATTERNS = (
    re.compile(r"(?:history|timeline|evolution|progression)\s+(?:of|for)\s+(.+)"),
    re.compile(
        r"how\s+(?:did|has|have)\s+(.+?)\s+"
        r"(?:evolve|evolved|change|changed|develop|developed|progress|progressed)\b"
    ),
    re.compile(r"(.+?)\s+used to\b"),
)

_TRAILING = (" over time", " over the years", " over the months", " historically")
_ARTICLES = ("the ", "a ", "an ", "my ", "our ", "your ")

#: H1 hardening — pronouns/stopwords must NOT become an entity: the executor's
#: substring resolver (LIKE '%X%' ORDER BY degree) would turn a 1-token entity
#: into the busiest node, yielding a wrong NON-empty timeline the auto-router
#: returns over hybrid. Reject them here so compile returns None -> fallback.
_STOPWORD_ENTITIES = frozenset(
    {
        "i",
        "we",
        "it",
        "they",
        "he",
        "she",
        "you",
        "me",
        "us",
        "them",
        "this",
        "that",
        "these",
        "those",
        "one",
        "thing",
        "stuff",
        "here",
        "there",
        "the",
        "a",
        "an",
        "my",
        "our",
        "your",
    }
)
_MIN_ENTITY_LEN = 2  # reject single-char tokens that substring-match any busy node


class TimelinePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    entity: str
    limit: int | None = None


def _clean_entity(s: str) -> str:
    s = s.strip().strip("?.!,;:'\"")
    for tail in _TRAILING:
        if s.endswith(tail):
            s = s[: -len(tail)].rstrip()
    for art in _ARTICLES:
        if s.startswith(art):
            s = s[len(art) :]
            break
    return s.strip()


def compile_timeline(query: str) -> TimelinePlan | None:
    q = (query or "").strip().lower()
    if not q:
        return None
    for pat in _ENTITY_PATTERNS:
        m = pat.search(q)
        if m:
            entity = _clean_entity(m.group(1))
            # H1: skip stopword/pronoun/too-short entities (keep scanning weaker
            # patterns in case one yields a real entity; else fall through -> None).
            if (
                not entity
                or len(entity) < _MIN_ENTITY_LEN
                or entity.lower() in _STOPWORD_ENTITIES
            ):
                continue
            return TimelinePlan(entity=entity)
    return None

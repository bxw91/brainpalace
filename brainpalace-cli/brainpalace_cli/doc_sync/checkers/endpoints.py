"""Endpoints surface: referential check that endpoint paths named in docs are live
routes. Gates DOCS (e.g. docs/API_REFERENCE.md); dashboard ENDPOINT_SURFACES is
separate. Scoped to `/path` tokens that follow an HTTP verb to avoid matching prose
slashes."""

from __future__ import annotations

import re
from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.referential import dangling_tokens

SURFACE = "endpoints"
# Path after an HTTP verb: `GET /query`, `POST /index`. Avoids bare prose slashes.
_EP_RE = re.compile(r"(?:GET|POST|PUT|PATCH|DELETE)\s+(/[a-zA-Z0-9/_{}-]*)")
# CHANGELOG is append-only history: it references endpoints by shorthand and may
# cite since-removed routes, so it must not be gated against the live route table.
_EXCLUDE_DOCS = frozenset({"CHANGELOG.md"})


def _normalize(path: str) -> str:
    return path.rstrip("/") or "/"


class EndpointsChecker:
    surface = SURFACE

    def __init__(self, doc_roots: list[Path]) -> None:
        self.doc_roots = [Path(r) for r in doc_roots]

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        docs: list[Path] = []
        for root in self.doc_roots:
            docs.extend(
                p for p in sorted(root.glob("*.md")) if p.name not in _EXCLUDE_DOCS
            )
        known = {_normalize(p) for p in snap.endpoints}
        records = dangling_tokens(
            docs,
            _EP_RE,
            set(snap.endpoints),
            SURFACE,
            "doc references unknown endpoint '{tok}'",
        )
        # Re-filter with trailing-slash normalization (dangling_tokens compares raw).
        return [r for r in records if _normalize(r.source_id) not in known]

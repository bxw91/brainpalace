"""Config surface: referential check that config keys named in docs are valid
schema dotpaths. Gates DOCS only — dashboard parity owns dashboard rendering.

Scoping is critical: a naive `section.field` match false-positives on filenames and
module paths (`config.yaml`, `dashboard.json`, `auth.py`, `brainpalace_cli.mcp_server`).
So a backticked dotted token is only considered a config reference when its FIRST
segment is a real config section AND it is not a file (known extension). Sections come
from the snapshot's bare top-level keys (config_dotpaths includes them)."""

from __future__ import annotations

import re
from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.referential import dangling_tokens

SURFACE = "config"
_FILE_EXTS = ("json", "yaml", "yml", "py", "md", "sh", "toml", "txt", "cfg", "ini")
# CHANGELOG is append-only history: it references config keys that may since have
# been renamed/removed, so it must not be gated against the live schema.
_EXCLUDE_DOCS = frozenset({"CHANGELOG.md"})


class ConfigChecker:
    surface = SURFACE

    def __init__(self, doc_roots: list[Path]) -> None:
        self.doc_roots = [Path(r) for r in doc_roots]

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        valid = set(snap.config_keys)
        # sections = the bare (no-dot) entries in config_keys (top-level keys).
        sections = sorted(k for k in valid if "." not in k)
        if not sections:
            return []
        # Backticked `<section>.<rest>` — first segment must be a real section.
        sect_alt = "|".join(re.escape(s) for s in sections)
        pattern = re.compile(rf"`((?:{sect_alt})\.[a-z0-9_.]+)`")
        docs: list[Path] = []
        for root in self.doc_roots:
            docs.extend(
                p for p in sorted(root.glob("*.md")) if p.name not in _EXCLUDE_DOCS
            )
        recs = dangling_tokens(
            docs,
            pattern,
            valid,
            SURFACE,
            "doc references unknown config key '{tok}'",
        )
        # Post-filter: drop file tokens like `dashboard.json` (last segment is a
        # file extension) — `dashboard` is a real section but this is a filename.
        return [r for r in recs if r.source_id.split(".")[-1] not in _FILE_EXTS]

"""Freshness checker treats machine-owned regions (contract frontmatter +
GENERATED blocks) as metadata, so a pure doc-sync regen does not trip
lint:doc-freshness (spec resolution 11/G). See scripts/check_doc_freshness.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_doc_freshness.py"
_spec = importlib.util.spec_from_file_location("check_doc_freshness", _SCRIPT)
freshness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(freshness)  # type: ignore[union-attr]


BASE = """\
---
name: brainpalace-index
description: Index documents for semantic search
parameters:
  - name: force
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-09
---
# Index

## Purpose
Human prose describing what index does.

### Flags
<!--GENERATED:flags-->
| --force | bool | false | Force |
<!--/GENERATED-->
"""


def test_contract_frontmatter_change_does_not_change_human_portion():
    changed = BASE.replace(
        "  - name: force\n    type: bool\n    required: false\n    default: false",
        "  - name: force\n    type: bool\n    required: false\n    default: true\n"
        '  - name: url\n    type: text\n    required: false\n    default: ""',
    )
    assert freshness.human_portion(BASE) == freshness.human_portion(changed)


def test_generated_block_change_does_not_change_human_portion():
    changed = BASE.replace(
        "| --force | bool | false | Force |",
        "| --force | bool | false | TOTALLY NEW |",
    )
    assert freshness.human_portion(BASE) == freshness.human_portion(changed)


def test_last_validated_change_does_not_change_human_portion():
    changed = BASE.replace("last_validated: 2026-06-09", "last_validated: 2026-06-13")
    assert freshness.human_portion(BASE) == freshness.human_portion(changed)


def test_prose_change_changes_human_portion():
    changed = BASE.replace(
        "Human prose describing what index does.", "Completely different prose."
    )
    assert freshness.human_portion(BASE) != freshness.human_portion(changed)


def test_human_frontmatter_change_changes_human_portion():
    # description is human-owned (not contract) — a real edit must still count.
    changed = BASE.replace(
        "description: Index documents for semantic search", "description: NEW desc"
    )
    assert freshness.human_portion(BASE) != freshness.human_portion(changed)


def test_creating_flags_section_does_not_change_human_portion():
    # The doc-sync migration appends `### Flags\n<!--GENERATED:flags-->...` to a doc
    # that had none. The heading is constant machine-emitted text, so creating the
    # whole section must read as metadata — not a human edit (would trip freshness).
    no_section = BASE.replace(
        "\n### Flags\n<!--GENERATED:flags-->\n| --force | bool | false | Force |\n"
        "<!--/GENERATED-->\n",
        "",
    )
    assert "### Flags" not in no_section  # sanity: removal worked
    assert freshness.human_portion(no_section) == freshness.human_portion(BASE)


# --- content_hash gate (the same-day-edit blind spot fix) ----------------- #
# content_hash compares WHAT the content is, not WHEN it changed, so an edit made
# the same calendar day as validation is still caught. The recorded hash lives in
# the sidecar manifest (scripts/doc_freshness.json), not in the doc frontmatter.


def test_last_validated_change_does_not_change_content_hash():
    changed = BASE.replace("last_validated: 2026-06-09", "last_validated: 2026-06-13")
    assert freshness.content_hash(BASE) == freshness.content_hash(changed)


def test_legacy_validated_hash_line_does_not_change_content_hash():
    # A stray legacy validated_hash frontmatter line must not affect the hash.
    changed = BASE.replace(
        "last_validated: 2026-06-09",
        "last_validated: 2026-06-09\nvalidated_hash: deadbeef",
    )
    assert freshness.content_hash(BASE) == freshness.content_hash(changed)


def test_generated_block_change_does_not_change_content_hash():
    changed = BASE.replace(
        "| --force | bool | false | Force |", "| --force | bool | false | NEW |"
    )
    assert freshness.content_hash(BASE) == freshness.content_hash(changed)


def test_prose_change_changes_content_hash():
    changed = BASE.replace(
        "Human prose describing what index does.", "Completely different prose."
    )
    assert freshness.content_hash(BASE) != freshness.content_hash(changed)


def test_manifest_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "doc_freshness.json"
    monkeypatch.setattr(freshness, "MANIFEST_PATH", str(path))
    assert freshness.load_manifest() == {}  # absent -> empty
    freshness.save_manifest({"b.md": "2", "a.md": "1"})
    # Persisted sorted by key, and round-trips.
    assert path.read_text().splitlines()[1].strip().startswith('"a.md"')
    assert freshness.load_manifest() == {"a.md": "1", "b.md": "2"}


def test_fresh_when_recorded_hash_matches():
    # Manifest records content_hash -> gate sees a match (fresh).
    recorded = freshness.content_hash(BASE)
    assert recorded == freshness.content_hash(BASE)


def test_stale_when_prose_edited_after_recording():
    # Record the hash, then edit prose — recorded != recomputed (the same-day
    # blind spot the hash gate closes; no date moved).
    recorded = freshness.content_hash(BASE)
    edited = BASE.replace(
        "Human prose describing what index does.", "Sneaky later edit."
    )
    assert recorded != freshness.content_hash(edited)

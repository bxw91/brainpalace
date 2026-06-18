"""Tests for the per-file targeting of scripts/add_audit_metadata.py.

The stamp script defaults to a repo-wide run that REBUILDS the manifest (pruning
orphan entries). Passing explicit file paths must instead stamp only those docs
and PRESERVE every other manifest entry — otherwise targeting one doc would wipe
the rest of the manifest. These tests lock that distinction.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "add_audit_metadata.py"
_spec = importlib.util.spec_from_file_location("add_audit_metadata", _SCRIPT)
stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp)  # type: ignore[union-attr]


def test_full_run_seeds_empty_manifest_to_prune_orphans():
    old = {"docs/A.md": "1", "docs/GONE.md": "2"}
    assert stamp.build_new_manifest(old, targeted=False) == {}


def test_targeted_run_preserves_other_manifest_entries():
    old = {"docs/A.md": "1", "docs/B.md": "2"}
    seed = stamp.build_new_manifest(old, targeted=True)
    assert seed == old
    # Must be an independent copy: mutating the seed must not touch old.
    seed["docs/A.md"] = "changed"
    assert old["docs/A.md"] == "1"


def test_resolve_targets_accepts_audited_file(tmp_path):
    root = str(tmp_path)
    f = tmp_path / "docs" / "A.md"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    all_files = [os.path.abspath(str(f))]
    assert stamp.resolve_targets(all_files, ["docs/A.md"], root) == all_files


def test_resolve_targets_accepts_absolute_path(tmp_path):
    root = str(tmp_path)
    f = tmp_path / "docs" / "A.md"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    ap = os.path.abspath(str(f))
    all_files = [ap]
    assert stamp.resolve_targets(all_files, [ap], root) == all_files


def test_resolve_targets_rejects_non_audited_file(tmp_path):
    root = str(tmp_path)
    audited = tmp_path / "docs" / "A.md"
    audited.parent.mkdir(parents=True)
    audited.write_text("x")
    (tmp_path / "NOTES.md").write_text("y")
    with pytest.raises(SystemExit):
        stamp.resolve_targets([os.path.abspath(str(audited))], ["NOTES.md"], root)

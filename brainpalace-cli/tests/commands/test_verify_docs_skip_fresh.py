"""Tests for the `verify-docs` skip-fresh filter.

Skip-fresh is ON by default in every mode. A doc is skipped only when it is BOTH
recently validated (age < N days) AND unchanged since (its authored content still
matches the freshness manifest hash) — so a doc edited after validation is always
re-verified. The window must sit below the weekly cadence (so last week's sweep
re-verifies) and the boundary is `age < days` ⇒ skip, `age >= days` ⇒ keep.
"""

from __future__ import annotations

from datetime import date, timedelta

import brainpalace_cli.commands.verify_docs as vd


def test_default_window_below_weekly_cadence() -> None:
    """The default must be > 0 (on) and < 7 (so last week's sweep re-verifies)."""
    assert 0 < vd.DEFAULT_SKIP_FRESH_DAYS < 7


def test_parse_iso_date() -> None:
    assert vd._parse_iso_date("2026-06-16") == date(2026, 6, 16)
    assert vd._parse_iso_date("  2026-06-16  ") == date(2026, 6, 16)
    assert vd._parse_iso_date(None) is None
    assert vd._parse_iso_date("") is None
    assert vd._parse_iso_date("not-a-date") is None


def _write_doc(root, name: str, *, validated: date | None) -> str:
    fm = f"---\nlast_validated: {validated.isoformat()}\n---\n" if validated else ""
    content = fm + f"# {name}\n\nprose body for {name}\n"
    (root / name).write_text(content, encoding="utf-8")
    return content


def test_filter_fresh_date_and_hash(tmp_path, monkeypatch) -> None:
    """Skipped iff recent (age < N) AND content hash matches the manifest."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    fresh = vd._freshness()
    today = date.today()

    bodies = {
        "fresh_unchanged.md": _write_doc(
            tmp_path, "fresh_unchanged.md", validated=today - timedelta(days=3)
        ),
        "fresh_edited.md": _write_doc(
            tmp_path, "fresh_edited.md", validated=today - timedelta(days=3)
        ),
        "boundary.md": _write_doc(
            tmp_path, "boundary.md", validated=today - timedelta(days=6)
        ),
        "stale.md": _write_doc(
            tmp_path, "stale.md", validated=today - timedelta(days=30)
        ),
        "undated.md": _write_doc(tmp_path, "undated.md", validated=None),
        "not_in_manifest.md": _write_doc(
            tmp_path, "not_in_manifest.md", validated=today - timedelta(days=1)
        ),
    }

    # Manifest: correct hash for all EXCEPT fresh_edited.md (simulates an edit
    # after validation → hash mismatch) and not_in_manifest.md (absent).
    manifest = {
        name: fresh.content_hash(body)
        for name, body in bodies.items()
        if name not in ("fresh_edited.md", "not_in_manifest.md")
    }
    manifest["fresh_edited.md"] = "stale-hash-from-before-the-edit"
    monkeypatch.setattr(fresh, "load_manifest", lambda: manifest)
    # All docs here have been prose-verified — isolate the date/hash logic from the
    # provenance gate (covered by test_filter_fresh_requires_prose_verification).
    monkeypatch.setattr(
        vd, "_prose_verified_docs", lambda: {*bodies.keys(), "missing.md"}
    )

    entries = [
        {"path": p, "trigger": "explicit", "affected_by": []}
        for p in (*bodies.keys(), "missing.md")
    ]
    kept, skipped = vd._filter_fresh(entries, days=6)

    # Only the recent-AND-unchanged doc is skipped.
    assert skipped == ["fresh_unchanged.md"]
    kept_paths = {e["path"] for e in kept}
    assert kept_paths == {
        "fresh_edited.md",  # recent but hash changed → re-verify
        "boundary.md",  # age == 6 (not < 6)
        "stale.md",  # too old
        "undated.md",  # no stamp
        "not_in_manifest.md",  # absent from manifest → unchanged is False
        "missing.md",  # unreadable
    }


def test_filter_fresh_reset_epoch(tmp_path, monkeypatch) -> None:
    """A reset epoch keeps docs validated before it, even if otherwise fresh."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    fresh = vd._freshness()
    today = date.today()

    bodies = {
        "before_reset.md": _write_doc(
            tmp_path, "before_reset.md", validated=today - timedelta(days=3)
        ),
        "after_reset.md": _write_doc(tmp_path, "after_reset.md", validated=today),
    }
    manifest = {name: fresh.content_hash(body) for name, body in bodies.items()}
    monkeypatch.setattr(fresh, "load_manifest", lambda: manifest)
    monkeypatch.setattr(vd, "_prose_verified_docs", lambda: set(bodies.keys()))
    entries = [{"path": p, "trigger": "explicit", "affected_by": []} for p in bodies]

    # Reset epoch = yesterday: the doc stamped 3 days ago is now stale (kept);
    # the one stamped today is on/after the epoch and still fresh (skipped).
    kept, skipped = vd._filter_fresh(
        entries, days=6, reset_epoch=today - timedelta(days=1)
    )
    assert skipped == ["after_reset.md"]
    assert {e["path"] for e in kept} == {"before_reset.md"}


def test_filter_fresh_requires_prose_verification(tmp_path, monkeypatch) -> None:
    """A doc whose `last_validated` came only from the human audit tool (never in
    the verdict cache) must NOT be skipped, even when it is recent and unchanged.

    This is the provenance bug: skip-fresh keyed only on `last_validated`, which is
    written by both `add_audit_metadata.py` and `verify-docs --record`, so
    never-prose-judged docs looked fresh and were silently dropped from sweeps.
    """
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    fresh = vd._freshness()
    today = date.today()

    bodies = {
        "prose_verified.md": _write_doc(
            tmp_path, "prose_verified.md", validated=today - timedelta(days=2)
        ),
        "human_audited_only.md": _write_doc(
            tmp_path, "human_audited_only.md", validated=today - timedelta(days=2)
        ),
    }
    manifest = {name: fresh.content_hash(body) for name, body in bodies.items()}
    monkeypatch.setattr(fresh, "load_manifest", lambda: manifest)
    # Only the first doc has a prose verdict on record.
    monkeypatch.setattr(vd, "_prose_verified_docs", lambda: {"prose_verified.md"})

    entries = [{"path": p, "trigger": "all", "affected_by": []} for p in bodies]
    kept, skipped = vd._filter_fresh(entries, days=6)

    assert skipped == ["prose_verified.md"]
    assert {e["path"] for e in kept} == {"human_audited_only.md"}


def test_prose_verified_docs_reads_cache(monkeypatch) -> None:
    """`_prose_verified_docs` returns the docs present in the verdict cache and
    ignores the reserved marker key / malformed entries."""
    monkeypatch.setattr(
        vd,
        "_load_cache",
        lambda: {
            vd._MARKER_KEY: {"base": "main", "fingerprint": "x"},
            "h1": {"doc": "docs/A.md", "verdict": "SUPPORTED"},
            "h2": {"doc": "docs/A.md", "verdict": "CONTRADICTED"},
            "h3": {"doc": "docs/B.md", "verdict": "SUPPORTED"},
            "h4": {"verdict": "SUPPORTED"},  # no doc field → ignored
            "h5": "not-a-dict",  # malformed → ignored
        },
    )
    assert vd._prose_verified_docs() == {"docs/A.md", "docs/B.md"}


def test_reset_epoch_roundtrip(tmp_path, monkeypatch) -> None:
    """`_stamp_reset` persists today's epoch; `_load_reset_epoch` reads it back."""
    monkeypatch.setattr(vd, "_SWEEP_STATE", tmp_path / ".doc-verify-sweep.json")
    assert vd._load_reset_epoch() is None
    stamped = vd._stamp_reset()
    assert stamped == date.today().isoformat()
    assert vd._load_reset_epoch() == date.today()
    # Reset must not clobber an existing weekly-clock key.
    vd._stamp_weekly_clock()
    assert vd._load_reset_epoch() == date.today()

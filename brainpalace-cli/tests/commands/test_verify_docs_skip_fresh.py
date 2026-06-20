"""Tests for the `verify-docs` relation-based skip.

A doc is skipped only when it is prose-verified, its prose is unchanged (manifest
hash match), it is fully clean (every verdict SUPPORTED), AND every grounded
file/dir relation still hashes the same. There is no time window: a stamp's age is
irrelevant. `--force` skips nothing.
"""

from __future__ import annotations

import brainpalace_cli.commands.verify_docs as vd


def _doc(tmp_path, name: str, body: str = "# d\nbody\n") -> str:
    (tmp_path / name).write_text(body, encoding="utf-8")
    return body


def _setup(tmp_path, monkeypatch, *, cache: dict, prose_verified: set, clean: set):
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    fresh = vd._freshness()
    monkeypatch.setattr(vd, "_load_cache", lambda: cache)
    monkeypatch.setattr(vd, "_prose_verified_docs", lambda: prose_verified)
    monkeypatch.setattr(vd, "_clean_verified_docs", lambda c: clean)
    return fresh


def test_skips_clean_doc_with_unchanged_relation(tmp_path, monkeypatch) -> None:
    body = _doc(tmp_path, "A.md")
    (tmp_path / "x.py").write_text("code\n", encoding="utf-8")
    # _REPO_ROOT must be patched before computing stored so _relation_hash
    # resolves x.py under tmp_path, not the real repo root.
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    stored = vd._relation_hash(["x.py"])
    fresh = _setup(
        tmp_path,
        monkeypatch,
        cache={
            "h": {
                "doc": "A.md",
                "verdict": "SUPPORTED",
                "grounding_files": ["x.py"],
                "grounding_hash": stored,
            }
        },
        prose_verified={"A.md"},
        clean={"A.md"},
    )
    monkeypatch.setattr(
        fresh, "load_manifest", lambda: {"A.md": fresh.content_hash(body)}
    )
    entries = [{"path": "A.md", "trigger": "all", "affected_by": []}]
    kept, skipped = vd._filter_fresh(entries)
    assert skipped == ["A.md"]
    assert kept == []


def test_keeps_doc_when_relation_changed(tmp_path, monkeypatch) -> None:
    body = _doc(tmp_path, "A.md")
    (tmp_path / "x.py").write_text("code\n", encoding="utf-8")
    # _REPO_ROOT must be patched before computing stored so _relation_hash
    # resolves x.py under tmp_path, not the real repo root.
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    stored = vd._relation_hash(["x.py"])
    fresh = _setup(
        tmp_path,
        monkeypatch,
        cache={
            "h": {
                "doc": "A.md",
                "verdict": "SUPPORTED",
                "grounding_files": ["x.py"],
                "grounding_hash": stored,
            }
        },
        prose_verified={"A.md"},
        clean={"A.md"},
    )
    monkeypatch.setattr(
        fresh, "load_manifest", lambda: {"A.md": fresh.content_hash(body)}
    )
    (tmp_path / "x.py").write_text("CODE CHANGED\n", encoding="utf-8")  # relation moved
    entries = [{"path": "A.md", "trigger": "all", "affected_by": []}]
    kept, skipped = vd._filter_fresh(entries)
    assert skipped == []
    assert [e["path"] for e in kept] == ["A.md"]


def test_keeps_doc_when_prose_edited(tmp_path, monkeypatch) -> None:
    _doc(tmp_path, "A.md")
    (tmp_path / "x.py").write_text("code\n", encoding="utf-8")
    # _REPO_ROOT must be patched before computing stored so _relation_hash
    # resolves x.py under tmp_path, not the real repo root.
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    stored = vd._relation_hash(["x.py"])
    fresh = _setup(
        tmp_path,
        monkeypatch,
        cache={
            "h": {
                "doc": "A.md",
                "verdict": "SUPPORTED",
                "grounding_files": ["x.py"],
                "grounding_hash": stored,
            }
        },
        prose_verified={"A.md"},
        clean={"A.md"},
    )
    # Manifest hash is for OLD prose; the file on disk differs → prose edited.
    monkeypatch.setattr(fresh, "load_manifest", lambda: {"A.md": "stale-hash"})
    entries = [{"path": "A.md", "trigger": "all", "affected_by": []}]
    kept, skipped = vd._filter_fresh(entries)
    assert skipped == []


def test_keeps_doc_never_prose_verified(tmp_path, monkeypatch) -> None:
    body = _doc(tmp_path, "A.md")
    fresh = _setup(tmp_path, monkeypatch, cache={}, prose_verified=set(), clean=set())
    monkeypatch.setattr(
        fresh, "load_manifest", lambda: {"A.md": fresh.content_hash(body)}
    )
    entries = [{"path": "A.md", "trigger": "all", "affected_by": []}]
    kept, skipped = vd._filter_fresh(entries)
    assert skipped == []


def test_keeps_doc_not_fully_clean(tmp_path, monkeypatch) -> None:
    body = _doc(tmp_path, "A.md")
    fresh = _setup(
        tmp_path,
        monkeypatch,
        cache={"h": {"doc": "A.md", "verdict": "CONTRADICTED"}},
        prose_verified={"A.md"},
        clean=set(),  # not clean
    )
    monkeypatch.setattr(
        fresh, "load_manifest", lambda: {"A.md": fresh.content_hash(body)}
    )
    entries = [{"path": "A.md", "trigger": "all", "affected_by": []}]
    kept, skipped = vd._filter_fresh(entries)
    assert skipped == []


def test_force_skips_nothing(tmp_path, monkeypatch) -> None:
    body = _doc(tmp_path, "A.md")
    (tmp_path / "x.py").write_text("code\n", encoding="utf-8")
    # _REPO_ROOT must be patched before computing stored so _relation_hash
    # resolves x.py under tmp_path, not the real repo root.
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    stored = vd._relation_hash(["x.py"])
    fresh = _setup(
        tmp_path,
        monkeypatch,
        cache={
            "h": {
                "doc": "A.md",
                "verdict": "SUPPORTED",
                "grounding_files": ["x.py"],
                "grounding_hash": stored,
            }
        },
        prose_verified={"A.md"},
        clean={"A.md"},
    )
    monkeypatch.setattr(
        fresh, "load_manifest", lambda: {"A.md": fresh.content_hash(body)}
    )
    entries = [{"path": "A.md", "trigger": "all", "affected_by": []}]
    kept, skipped = vd._filter_fresh(entries, force=True)
    assert skipped == []
    assert [e["path"] for e in kept] == ["A.md"]


def test_prose_verified_docs_reads_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        vd,
        "_load_cache",
        lambda: {
            vd._MARKER_KEY: {"base": "main", "fingerprint": "x"},
            "h1": {"doc": "docs/A.md", "verdict": "SUPPORTED"},
            # A second record for the same doc must not change the result.
            "h2": {"doc": "docs/A.md", "verdict": "CONTRADICTED"},
            "h3": {"doc": "docs/B.md", "verdict": "SUPPORTED"},
            "h4": {"verdict": "SUPPORTED"},  # no doc field → ignored
            "h5": "not-a-dict",  # malformed → ignored
        },
    )
    assert vd._prose_verified_docs() == {"docs/A.md", "docs/B.md"}

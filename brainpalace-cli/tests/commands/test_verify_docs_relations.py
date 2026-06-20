"""Tests for `verify-docs` file/dir grounding-relation hashing.

A claim records the files/dirs it grounds on. Re-verify fires only when one of
those paths changes (file edited, dir gains/loses/edits a member, path deleted).
Pure filesystem — no index server.
"""

from __future__ import annotations

import brainpalace_cli.commands.verify_docs as vd


def test_path_content_hash_file_changes_with_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    h1 = vd._path_content_hash("a.py")
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    h2 = vd._path_content_hash("a.py")
    assert h1 and h2 and h1 != h2


def test_path_content_hash_missing_is_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    assert vd._path_content_hash("nope.py") is None


def test_path_content_hash_dir_changes_when_member_added(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    d = tmp_path / "providers"
    d.mkdir()
    (d / "openai.py").write_text("openai\n", encoding="utf-8")
    h1 = vd._path_content_hash("providers")
    (d / "cohere.py").write_text("cohere\n", encoding="utf-8")  # new member
    h2 = vd._path_content_hash("providers")
    assert h1 and h2 and h1 != h2


def test_relation_hash_order_independent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b\n", encoding="utf-8")
    assert vd._relation_hash(["a.py", "b.py"]) == vd._relation_hash(["b.py", "a.py"])


def test_relation_hash_none_when_any_path_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("a\n", encoding="utf-8")
    assert vd._relation_hash(["a.py", "gone.py"]) is None
    assert vd._relation_hash([]) is None


def test_relation_unchanged_true_when_hash_matches(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("a\n", encoding="utf-8")
    rec = {
        "doc": "docs/A.md",
        "grounding_files": ["a.py"],
        "grounding_hash": vd._relation_hash(["a.py"]),
    }
    assert vd._relation_unchanged(rec) is True


def test_relation_unchanged_false_when_file_changed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "a.py").write_text("a\n", encoding="utf-8")
    rec = {
        "doc": "docs/A.md",
        "grounding_files": ["a.py"],
        "grounding_hash": vd._relation_hash(["a.py"]),
    }
    (tmp_path / "a.py").write_text("CHANGED\n", encoding="utf-8")
    assert vd._relation_unchanged(rec) is False


def test_relation_unchanged_true_when_no_relation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    assert (
        vd._relation_unchanged({"doc": "docs/A.md", "verdict": "UNVERIFIABLE"}) is True
    )


def test_dir_hash_ignores_pycache_and_pyc(tmp_path, monkeypatch) -> None:
    """Generated noise must not flip a grounded dir's hash — else the doc re-verifies
    every run for no real source change."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "mod.py").write_text("real\n", encoding="utf-8")
    h1 = vd._path_content_hash("pkg")
    cache = d / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-312.pyc").write_bytes(b"\x00bytecode")
    (d / "mod.pyc").write_bytes(b"\x00more")
    h2 = vd._path_content_hash("pkg")
    assert h1 == h2  # noise ignored


def test_code_paths_from_grounding(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    audited = {"docs/A.md"}
    assert vd._code_paths_from_grounding("src/x.py: snippet", audited) == ["src/x.py"]
    # code path is kept, the doc mention is dropped
    assert vd._code_paths_from_grounding("src/x.py (see docs/A.md)", audited) == [
        "src/x.py"
    ]
    # absolute path normalised to repo-relative
    assert vd._code_paths_from_grounding(f"{tmp_path}/src/y.py", audited) == [
        "src/y.py"
    ]
    # no code path → empty
    assert vd._code_paths_from_grounding("docs/A.md", audited) == []
    assert vd._code_paths_from_grounding("see the docs", audited) == []


def test_build_packet_marks_cached_verdicts_fresh_or_stale(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "A.md").write_text("# A\nbody\n", encoding="utf-8")
    (tmp_path / "fresh.py").write_text("a\n", encoding="utf-8")
    (tmp_path / "stale.py").write_text("b\n", encoding="utf-8")
    fresh_hash = vd._relation_hash(["fresh.py"])
    cache = {
        "h1": {
            "doc": "A.md",
            "claim": "fresh claim",
            "verdict": "SUPPORTED",
            "grounding_files": ["fresh.py"],
            "grounding_hash": fresh_hash,
        },
        "h2": {
            "doc": "A.md",
            "claim": "stale claim",
            "verdict": "SUPPORTED",
            "grounding_files": ["stale.py"],
            "grounding_hash": "OLD-HASH",  # != current → stale
        },
    }
    monkeypatch.setattr(vd, "_load_cache", lambda: cache)
    packet = vd._build_packet([{"path": "A.md", "trigger": "all"}], base="-")
    cached = {c["claim"]: c["fresh"] for c in packet["docs"][0]["cached_verdicts"]}
    assert cached == {"fresh claim": True, "stale claim": False}


def test_doc_paths_from_grounding(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    audited = {"docs/A.md", "docs/B.md", "docs/SELF.md"}
    # audited dep kept
    assert vd._doc_paths_from_grounding("docs/A.md", audited, "docs/SELF.md") == [
        "docs/A.md"
    ]
    # excluded / unknown .md dropped
    assert (
        vd._doc_paths_from_grounding("docs/CHANGELOG.md", audited, "docs/SELF.md") == []
    )
    assert (
        vd._doc_paths_from_grounding("docs/UNKNOWN.md", audited, "docs/SELF.md") == []
    )
    # self-reference dropped
    assert vd._doc_paths_from_grounding("docs/SELF.md", audited, "docs/SELF.md") == []
    # multiple, sorted + deduped, self removed
    assert vd._doc_paths_from_grounding(
        "docs/B.md docs/A.md docs/SELF.md", audited, "docs/SELF.md"
    ) == ["docs/A.md", "docs/B.md"]
    # code path is not a doc dep
    assert vd._doc_paths_from_grounding("src/x.py", audited, "docs/SELF.md") == []


def test_grounding_path_hash_md_ignores_frontmatter(tmp_path, monkeypatch) -> None:
    """A .md dep is hashed by authored body, so a last_validated re-stamp (frontmatter
    only) does NOT move the hash — else the dependent re-grounds forever."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    body = "# D\n\nThe system supports 5 providers.\n"
    (tmp_path / "D.md").write_text(
        "---\nlast_validated: 2026-01-01\n---\n" + body, encoding="utf-8"
    )
    h1 = vd._grounding_path_hash("D.md")
    # re-stamp: bump only the frontmatter date
    (tmp_path / "D.md").write_text(
        "---\nlast_validated: 2026-06-19\n---\n" + body, encoding="utf-8"
    )
    h2 = vd._grounding_path_hash("D.md")
    assert h1 and h2 and h1 == h2  # authored body unchanged


def test_grounding_path_hash_md_moves_on_body_change(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "D.md").write_text("# D\n\n5 providers.\n", encoding="utf-8")
    h1 = vd._grounding_path_hash("D.md")
    (tmp_path / "D.md").write_text("# D\n\n4 providers.\n", encoding="utf-8")
    h2 = vd._grounding_path_hash("D.md")
    assert h1 and h2 and h1 != h2


def test_grounding_path_hash_code_uses_raw_bytes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "x.py").write_text("a = 1\n", encoding="utf-8")
    assert vd._grounding_path_hash("x.py") == vd._path_content_hash("x.py")


def test_relation_hash_uses_md_body_for_dep(tmp_path, monkeypatch) -> None:
    """_relation_hash over a .md dep must match across a frontmatter-only re-stamp."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    body = "# D\n\nbody\n"
    (tmp_path / "D.md").write_text(
        "---\nlast_validated: 2026-01-01\n---\n" + body, encoding="utf-8"
    )
    h1 = vd._relation_hash(["D.md"])
    (tmp_path / "D.md").write_text(
        "---\nlast_validated: 2026-06-19\n---\n" + body, encoding="utf-8"
    )
    assert vd._relation_hash(["D.md"]) == h1


def test_packet_feeds_raw_verdict_for_doc_dep(tmp_path, monkeypatch) -> None:
    """A doc-dep claim settled to PENDING is fed back by its raw SUPPORTED so the agent
    can echo it verbatim (no re-ground)."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "E.md").write_text("# E\nbody\n", encoding="utf-8")
    (tmp_path / "D.md").write_text("# D\nbody\n", encoding="utf-8")
    cache = {
        "h1": {
            "doc": "E.md",
            "claim": "rests on D",
            "grounding": "D.md",
            "raw_verdict": "SUPPORTED",
            "verdict": "PENDING",
            "grounding_files": ["D.md"],
            "grounding_hash": vd._relation_hash(["D.md"]),
        },
    }
    monkeypatch.setattr(vd, "_load_cache", lambda: cache)
    packet = vd._build_packet([{"path": "E.md", "trigger": "all"}], base="-")
    cv = packet["docs"][0]["cached_verdicts"]
    assert len(cv) == 1
    assert cv[0]["claim"] == "rests on D"
    assert cv[0]["verdict"] == "SUPPORTED"  # raw, not the settled PENDING
    assert cv[0]["fresh"] is True

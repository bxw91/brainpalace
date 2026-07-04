"""Plan C Task 4 — pure commit→triplets builder."""

from datetime import datetime, timezone

from brainpalace_server.indexing.git_graph import (
    author_id,
    commit_display,
    commit_id,
    commit_triplets,
)
from brainpalace_server.indexing.git_loader import CommitRecord


def _rec(**kw) -> CommitRecord:
    base = {
        "sha": "abc1234def5678",
        "author": "Ada L",
        "author_email": "Ada@Example.com",
        "committed_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "subject": "fix: the thing",
        "body": "",
        "files_changed": ["src/a.py", "src/gone.py"],
    }
    base.update(kw)
    return CommitRecord(**base)


def test_ids_and_display() -> None:
    assert commit_id("abc") == "git-commit:abc"
    assert author_id("Ada@Example.com") == "git-author:ada@example.com"
    d = commit_display(_rec())
    assert d.startswith("abc1234d ")
    assert "fix: the thing" in d
    long = commit_display(_rec(subject="x" * 200))
    assert len(long) <= 80


def test_modifies_only_existing_files() -> None:
    triplets = commit_triplets(_rec(), "/repo", existing_file_ids={"/repo/src/a.py"})
    by_pred = {}
    for t in triplets:
        by_pred.setdefault(t.predicate, []).append(t)
    assert len(by_pred["modifies"]) == 1
    m = by_pred["modifies"][0]
    assert m.object_id == "/repo/src/a.py"
    assert m.subject_id == "git-commit:abc1234def5678"
    assert m.subject_type == "Commit" and m.object_type == "File"
    assert m.source_file == "commit:abc1234def5678"
    assert m.source_chunk_id == "git_commit:abc1234def5678"


def test_authored_by_always_present() -> None:
    triplets = commit_triplets(_rec(), "/repo", existing_file_ids=set())
    auth = [t for t in triplets if t.predicate == "authored_by"]
    assert len(auth) == 1
    assert auth[0].object_id == "git-author:ada@example.com"
    assert auth[0].object_name == "Ada L"
    assert auth[0].subject_type == "Commit" and auth[0].object_type == "Author"


def test_bulk_commit_skips_modifies() -> None:
    rec = _rec(files_changed=[f"f{i}.py" for i in range(60)])
    existing = {f"/repo/f{i}.py" for i in range(60)}
    triplets = commit_triplets(rec, "/repo", existing, max_cochange_files=50)
    assert [t.predicate for t in triplets] == ["authored_by"]


def test_empty_email_skips_authored_by() -> None:
    triplets = commit_triplets(_rec(author_email=""), "/repo", existing_file_ids=set())
    assert triplets == []

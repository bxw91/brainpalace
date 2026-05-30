"""Phase 130 — GitHistoryLoader: parse `git log` into commit records."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brainpalace_server.indexing.git_loader import CommitRecord, load_commits


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str, body: str = "") -> str:
    (repo / name).write_text(f"content of {name}\n")
    _run(repo, "add", name)
    msg = f"add {name}" + (f"\n\n{body}" if body else "")
    _run(repo, "commit", "-m", msg)
    return _run(repo, "rev-parse", "HEAD")


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.email", "dev@example.com")
    _run(repo, "config", "user.name", "Dev Person")
    return repo


def test_non_repo_returns_empty(tmp_path: Path) -> None:
    assert load_commits(tmp_path / "nope") == []


def test_parses_sha_author_date_subject(git_repo: Path) -> None:
    _commit(git_repo, "a.txt")
    _commit(git_repo, "b.txt", body="why we did this")

    commits = load_commits(git_repo)

    assert len(commits) == 2
    newest = commits[0]
    assert isinstance(newest, CommitRecord)
    assert len(newest.sha) == 40
    assert newest.author == "Dev Person"
    assert newest.author_email == "dev@example.com"
    assert newest.subject == "add b.txt"
    assert "why we did this" in newest.body
    assert newest.committed_at.tzinfo is not None  # ISO date with tz


def test_numstat_files_and_lines(git_repo: Path) -> None:
    _commit(git_repo, "a.txt")

    commits = load_commits(git_repo)

    rec = commits[0]
    assert "a.txt" in rec.files_changed
    assert rec.lines_added >= 1
    assert rec.lines_deleted == 0


def test_depth_limits_commit_count(git_repo: Path) -> None:
    for i in range(5):
        _commit(git_repo, f"f{i}.txt")

    commits = load_commits(git_repo, depth=2)

    assert len(commits) == 2


def test_since_sha_returns_only_newer_commits(git_repo: Path) -> None:
    first = _commit(git_repo, "a.txt")
    _commit(git_repo, "b.txt")
    _commit(git_repo, "c.txt")

    commits = load_commits(git_repo, since_sha=first)

    subjects = [c.subject for c in commits]
    assert subjects == ["add c.txt", "add b.txt"]
    assert all(c.sha != first for c in commits)

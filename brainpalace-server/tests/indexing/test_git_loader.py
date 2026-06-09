"""Phase 130 — GitHistoryLoader: parse `git log` into commit records."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from brainpalace_server.indexing.git_loader import (
    CommitRecord,
    _build_args,
    git_toplevel,
    load_commits,
    resolve_commit_scope,
)


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


def test_build_args_appends_path_filter() -> None:
    args = _build_args(depth=10, since_sha=None, paths=["services/api", "libs/x"])
    assert args[-3:] == ["--", "services/api", "libs/x"]


def test_build_args_path_filter_after_revision_range() -> None:
    args = _build_args(depth=10, since_sha="abc123", paths=["pkg"])
    assert "abc123..HEAD" in args
    assert args[-2:] == ["--", "pkg"]


def test_build_args_no_paths_no_separator() -> None:
    assert "--" not in _build_args(depth=10, since_sha=None, paths=[])


def test_build_args_depth_zero_is_unlimited() -> None:
    # depth <= 0 => no --max-count cap; walk the entire history.
    args = _build_args(depth=0, since_sha=None, paths=None)
    assert not any(a.startswith("--max-count") for a in args)
    args_pos = _build_args(depth=10, since_sha=None, paths=None)
    assert "--max-count=10" in args_pos


# ---------------------------------------------------------------------------
# Phase 1 — monorepo subdir scope helpers
# ---------------------------------------------------------------------------


def _init_monorepo(root: Path) -> Path:
    """Create a two-commit monorepo and return the subproject dir."""
    subprocess.run(
        ["git", "-C", str(root), "init", "-q"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@t.t"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "t"],
        check=True,
        capture_output=True,
    )
    (root / "rootfile.txt").write_text("root\n")
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "root commit"],
        check=True,
        capture_output=True,
    )
    sub = root / "projects" / "sub"
    sub.mkdir(parents=True)
    (sub / "a.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "sub commit"],
        check=True,
        capture_output=True,
    )
    return sub


def test_git_toplevel_returns_repo_root(tmp_path: Path) -> None:
    sub = _init_monorepo(tmp_path)
    assert git_toplevel(sub) == tmp_path.resolve()


def test_resolve_commit_scope_scopes_subdir_in_monorepo(tmp_path: Path) -> None:
    sub = _init_monorepo(tmp_path)
    scope = resolve_commit_scope(str(sub), path_filter=[])
    assert scope == [str(sub.resolve())]


def test_resolve_commit_scope_no_scope_when_project_is_repo_root(
    tmp_path: Path,
) -> None:
    _init_monorepo(tmp_path)
    scope = resolve_commit_scope(str(tmp_path), path_filter=[])
    assert scope == []


def test_resolve_commit_scope_respects_explicit_path_filter(tmp_path: Path) -> None:
    sub = _init_monorepo(tmp_path)
    scope = resolve_commit_scope(str(sub), path_filter=["only/this"])
    assert scope == ["only/this"]

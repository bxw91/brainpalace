"""Q3: GitignoreMatcher honours .git/info/exclude + global core.excludesFile."""

import shutil
import subprocess
from pathlib import Path

import pytest

from brainpalace_server.indexing import gitignore_matcher as gm
from brainpalace_server.indexing.gitignore_matcher import GitignoreMatcher

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture(autouse=True)
def _isolate_global_excludes(monkeypatch):
    """Default: ignore the host's real global core.excludesFile so these
    tests are deterministic. Individual tests may re-monkeypatch it."""
    monkeypatch.setattr(gm, "_global_excludes_path", lambda root: None)


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def test_info_exclude_is_honoured(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("secret.txt\n")
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    keep = tmp_path / "keep.txt"
    keep.write_text("x")

    matcher = GitignoreMatcher.from_project_root(tmp_path)
    assert matcher.is_ignored(secret) is True
    assert matcher.is_ignored(keep) is False


def test_nested_gitignore_negation_overrides_info_exclude(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("*.log\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / ".gitignore").write_text("!keep.log\n")
    keep = sub / "keep.log"
    keep.write_text("x")
    drop = sub / "drop.log"
    drop.write_text("x")

    matcher = GitignoreMatcher.from_project_root(tmp_path)
    assert matcher.is_ignored(drop) is True
    assert matcher.is_ignored(keep) is False


def test_global_excludes_file_is_honoured(tmp_path: Path, monkeypatch):
    _git_init(tmp_path)
    global_ignore = tmp_path / "global_ignore"
    global_ignore.write_text("*.bak\n")
    monkeypatch.setattr(gm, "_global_excludes_path", lambda root: global_ignore)
    bak = tmp_path / "data.bak"
    bak.write_text("x")
    txt = tmp_path / "data.txt"
    txt.write_text("x")

    matcher = GitignoreMatcher.from_project_root(tmp_path)
    assert matcher.is_ignored(bak) is True
    assert matcher.is_ignored(txt) is False


def test_worktree_info_exclude_is_honoured(tmp_path: Path):
    main = tmp_path / "main"
    main.mkdir()
    _git_init(main)
    # info/exclude lives in the common git dir
    (main / ".git" / "info" / "exclude").write_text("secret.txt\n")
    # a commit is required before `git worktree add`
    (main / "seed.txt").write_text("x")
    subprocess.run(["git", "-C", str(main), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "seed",
        ],
        check=True,
    )
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(wt)], check=True
    )
    secret = wt / "secret.txt"
    secret.write_text("x")
    keep = wt / "keep.txt"
    keep.write_text("x")

    matcher = GitignoreMatcher.from_project_root(wt)
    assert matcher.is_ignored(secret) is True
    assert matcher.is_ignored(keep) is False


def test_non_git_dir_falls_back_to_gitignore_only(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    ignored = tmp_path / "ignored.txt"
    ignored.write_text("x")
    matcher = GitignoreMatcher.from_project_root(tmp_path)
    assert matcher.is_ignored(ignored) is True

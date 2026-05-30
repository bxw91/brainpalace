"""Tests for GitignoreMatcher (Phase H)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.indexing.gitignore_matcher import GitignoreMatcher


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path


class TestRootGitignore:
    def test_no_gitignore_nothing_ignored(self, project_root: Path) -> None:
        matcher = GitignoreMatcher.from_project_root(project_root)
        assert matcher.is_ignored(project_root / "foo.py") is False

    def test_single_pattern_matches_file_in_root(self, project_root: Path) -> None:
        (project_root / ".gitignore").write_text("*.log\n")
        matcher = GitignoreMatcher.from_project_root(project_root)
        assert matcher.is_ignored(project_root / "app.log") is True
        assert matcher.is_ignored(project_root / "app.py") is False

    def test_directory_pattern_matches_files_under_dir(
        self, project_root: Path
    ) -> None:
        (project_root / ".gitignore").write_text("build/\n")
        (project_root / "build").mkdir()
        (project_root / "build" / "out.js").write_text("x")
        matcher = GitignoreMatcher.from_project_root(project_root)
        assert matcher.is_ignored(project_root / "build") is True
        assert matcher.is_ignored(project_root / "build" / "out.js") is True
        assert matcher.is_ignored(project_root / "src" / "out.js") is False

    def test_glob_double_star_matches_any_depth(self, project_root: Path) -> None:
        (project_root / ".gitignore").write_text("**/*.tmp\n")
        matcher = GitignoreMatcher.from_project_root(project_root)
        assert matcher.is_ignored(project_root / "a.tmp") is True
        assert matcher.is_ignored(project_root / "x" / "y" / "z.tmp") is True


class TestNestedGitignore:
    def test_child_gitignore_overrides_parent_ignore(self, project_root: Path) -> None:
        """Child `.gitignore` with `!foo.log` un-ignores a file the parent ignored."""
        (project_root / ".gitignore").write_text("*.log\n")
        (project_root / "sub").mkdir()
        (project_root / "sub" / ".gitignore").write_text("!keep.log\n")
        (project_root / "app.log").write_text("x")
        (project_root / "sub" / "keep.log").write_text("x")
        (project_root / "sub" / "drop.log").write_text("x")

        matcher = GitignoreMatcher.from_project_root(project_root)

        assert matcher.is_ignored(project_root / "app.log") is True
        assert matcher.is_ignored(project_root / "sub" / "keep.log") is False
        assert matcher.is_ignored(project_root / "sub" / "drop.log") is True

    def test_child_gitignore_adds_extra_ignores(self, project_root: Path) -> None:
        """Child `.gitignore` adds patterns that parent didn't have."""
        (project_root / ".gitignore").write_text("*.log\n")
        (project_root / "sub").mkdir()
        (project_root / "sub" / ".gitignore").write_text("*.cache\n")

        matcher = GitignoreMatcher.from_project_root(project_root)

        assert matcher.is_ignored(project_root / "sub" / "a.cache") is True
        # Parent's *.log still applies in sub/
        assert matcher.is_ignored(project_root / "sub" / "b.log") is True

    def test_dir_pattern_in_child_relative_to_child(self, project_root: Path) -> None:
        """`build/` in `sub/.gitignore` matches `sub/build/`, not `build/` at root."""
        (project_root / "build").mkdir()
        (project_root / "build" / "x.js").write_text("x")
        (project_root / "sub").mkdir()
        (project_root / "sub" / "build").mkdir()
        (project_root / "sub" / "build" / "y.js").write_text("x")
        (project_root / "sub" / ".gitignore").write_text("build/\n")

        matcher = GitignoreMatcher.from_project_root(project_root)

        assert matcher.is_ignored(project_root / "build" / "x.js") is False
        assert matcher.is_ignored(project_root / "sub" / "build" / "y.js") is True


class TestEdgeCases:
    def test_path_outside_project_root_not_ignored(self, tmp_path: Path) -> None:
        project_root = tmp_path / "proj"
        project_root.mkdir()
        (project_root / ".gitignore").write_text("*.log\n")
        outside = tmp_path / "other" / "a.log"
        outside.parent.mkdir()
        outside.write_text("x")

        matcher = GitignoreMatcher.from_project_root(project_root)

        assert matcher.is_ignored(outside) is False

    def test_unreadable_gitignore_skipped_gracefully(
        self, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gi = project_root / ".gitignore"
        gi.write_text("*.log\n")

        # Construct matcher AFTER making the file unreadable
        from pathlib import Path as RealPath

        orig_read_text = RealPath.read_text

        def fake_read_text(self: RealPath, *a, **kw) -> str:
            if self == gi:
                raise OSError("simulated permission denied")
            return orig_read_text(self, *a, **kw)

        monkeypatch.setattr(RealPath, "read_text", fake_read_text)

        matcher = GitignoreMatcher.from_project_root(project_root)
        # No spec was loaded — nothing ignored.
        assert matcher.is_ignored(project_root / "a.log") is False

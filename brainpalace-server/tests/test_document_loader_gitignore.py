"""Tests for DocumentLoader's .gitignore integration (Phase H)."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.indexing.document_loader import DocumentLoader
from brainpalace_server.indexing.gitignore_matcher import GitignoreMatcher


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.py").write_text("print('y')\n")
    (tmp_path / ".gitignore").write_text("build/\n")
    return tmp_path


class TestDocumentLoaderGitignore:
    def test_walk_pruned_skips_gitignored_dirs(self, project_root: Path) -> None:
        """`build/` listed in `.gitignore` is pruned from the walk."""
        matcher = GitignoreMatcher.from_project_root(project_root)
        loader = DocumentLoader(gitignore_matcher=matcher)

        files = list(loader._walk_pruned(project_root))
        names = {f.name for f in files}

        assert "app.py" in names
        assert "out.py" not in names

    def test_walk_pruned_skips_nested_brainpalace_project(
        self, project_root: Path
    ) -> None:
        """A subfolder with its own `.brainpalace/` is pruned (no double-index)."""
        sub = project_root / "subapp"
        sub.mkdir()
        (sub / ".brainpalace").mkdir()  # subapp is a separate BP project
        (sub / "nested.py").write_text("print('nested')\n")

        loader = DocumentLoader()
        names = {f.name for f in loader._walk_pruned(project_root)}

        assert "app.py" in names  # outer project still indexed
        assert "nested.py" not in names  # nested project pruned

    def test_walk_pruned_reincludes_after_nested_brainpalace_removed(
        self, project_root: Path
    ) -> None:
        """Pruning is dynamic: deleting the nested `.brainpalace/` re-includes it."""
        sub = project_root / "subapp"
        sub.mkdir()
        bp = sub / ".brainpalace"
        bp.mkdir()
        (sub / "nested.py").write_text("print('nested')\n")
        loader = DocumentLoader()

        assert "nested.py" not in {f.name for f in loader._walk_pruned(project_root)}

        bp.rmdir()  # user deletes the nested project's state dir
        assert "nested.py" in {f.name for f in loader._walk_pruned(project_root)}

    def test_walk_pruned_keeps_root_own_brainpalace_project(
        self, project_root: Path
    ) -> None:
        """The outer project's OWN root `.brainpalace/` must not prune the root."""
        (project_root / ".brainpalace").mkdir()  # this project's own state dir
        loader = DocumentLoader()
        names = {f.name for f in loader._walk_pruned(project_root)}

        assert "app.py" in names  # root still indexed despite its own .brainpalace

    def test_walk_pruned_skips_gitignored_files(self, project_root: Path) -> None:
        """Individual files matched by `.gitignore` are skipped."""
        (project_root / ".gitignore").write_text("**/*.tmp\n")
        (project_root / "src" / "scratch.tmp").write_text("x")
        (project_root / "src" / "real.py").write_text("y")

        matcher = GitignoreMatcher.from_project_root(project_root)
        loader = DocumentLoader(gitignore_matcher=matcher)

        files = list(loader._walk_pruned(project_root))
        names = {f.name for f in files}

        assert "real.py" in names
        assert "scratch.tmp" not in names

    def test_no_matcher_falls_back_to_existing_exclude_patterns(
        self, project_root: Path
    ) -> None:
        """When no matcher is injected, exclude_patterns behaviour is unchanged."""
        loader = DocumentLoader(exclude_patterns=["**/build"])
        # No matcher passed → only pattern-based excludes apply.
        files = list(loader._walk_pruned(project_root))
        names = {f.name for f in files}
        assert "out.py" not in names
        assert "app.py" in names

    @pytest.mark.asyncio
    async def test_load_files_honors_gitignore_via_temp_loader(
        self, project_root: Path
    ) -> None:
        """load_files() — the production indexing path — must honor .gitignore.

        load_files() builds an internal temp_loader; this test guards that the
        gitignore_matcher is forwarded so `build/` is skipped end-to-end.
        """
        matcher = GitignoreMatcher.from_project_root(project_root)
        loader = DocumentLoader(gitignore_matcher=matcher)

        docs = await loader.load_files(
            str(project_root), recursive=True, include_code=True
        )
        names = {Path(d.file_path).name for d in docs}

        assert "app.py" in names
        assert "out.py" not in names  # build/ is gitignored

    @pytest.mark.asyncio
    async def test_load_from_folder_empty_when_all_files_pruned(
        self, project_root: Path
    ) -> None:
        """A folder whose every file is gitignored yields [] — not a ValueError.

        Regression: an all-pruned folder produced an empty collected-file set
        that was passed straight to SimpleDirectoryReader(input_files=[]),
        which raised `ValueError: Must provide either input_dir or
        input_files`. Indexing such a folder is valid and must yield no docs.
        """
        matcher = GitignoreMatcher.from_project_root(project_root)
        loader = DocumentLoader(gitignore_matcher=matcher)

        # `build/` is gitignored by the fixture — every file under it is pruned.
        docs = await loader.load_from_folder(
            str(project_root / "build"), recursive=True
        )

        assert docs == []

"""Tests for B9 — the .brainpalace/ directory is always excluded from indexing."""

from pathlib import Path

from brainpalace_server.indexing.document_loader import DocumentLoader


def _seed(root: Path) -> None:
    """Create a real doc plus indexable files INSIDE .brainpalace/."""
    (root / "doc.md").write_text("# real doc\n")
    ab = root / ".brainpalace"
    ab.mkdir()
    # A supported (.md) file inside .brainpalace/ — without B9 it would be
    # collected, since extension filtering alone would not skip it.
    (ab / "leak.md").write_text("# index internals -- must NOT be indexed\n")
    logs = ab / "logs"
    logs.mkdir()
    (logs / "deep.md").write_text("# nested -- must NOT be indexed\n")


def test_brainpalace_excluded_with_default_patterns(tmp_path: Path) -> None:
    """.brainpalace/ is skipped under the default exclude patterns."""
    _seed(tmp_path)
    loader = DocumentLoader()
    files = loader.get_supported_files(str(tmp_path))
    names = {f.name for f in files}
    assert "doc.md" in names
    assert "leak.md" not in names
    assert "deep.md" not in names
    assert not any(".brainpalace" in str(f) for f in files)


def test_brainpalace_excluded_with_custom_patterns(tmp_path: Path) -> None:
    """.brainpalace/ stays excluded even when custom exclude_patterns omit it."""
    _seed(tmp_path)
    # Custom patterns that do NOT mention .brainpalace — must not override B9.
    loader = DocumentLoader(exclude_patterns=["**/node_modules/**"])
    files = loader.get_supported_files(str(tmp_path))
    assert not any(".brainpalace" in str(f) for f in files)
    assert any(f.name == "doc.md" for f in files)


def test_exclude_pattern_matches_single_file(tmp_path: Path) -> None:
    """A file-targeting glob excludes just that file, not the whole dir.

    Regression: exclude_patterns previously pruned directories only, so a
    pattern naming an individual file (e.g. CHANGELOG) was silently ignored and
    the file kept getting re-embedded on every change.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CHANGELOG.md").write_text("# changelog -- must NOT be indexed\n")
    (docs / "GUIDE.md").write_text("# guide -- must stay indexed\n")

    loader = DocumentLoader(exclude_patterns=["**/docs/CHANGELOG.md"])
    names = {f.name for f in loader.get_supported_files(str(tmp_path))}
    assert "CHANGELOG.md" not in names
    assert "GUIDE.md" in names  # sibling in the same dir is untouched


def test_exclude_bare_filename_pattern_matches_any_depth(tmp_path: Path) -> None:
    """`**/CHANGELOG.md` drops the file wherever it lives in the tree."""
    (tmp_path / "CHANGELOG.md").write_text("# root changelog\n")
    sub = tmp_path / "pkg" / "docs"
    sub.mkdir(parents=True)
    (sub / "CHANGELOG.md").write_text("# nested changelog\n")
    (sub / "README.md").write_text("# readme\n")

    loader = DocumentLoader(exclude_patterns=["**/CHANGELOG.md"])
    names = {f.name for f in loader.get_supported_files(str(tmp_path))}
    assert "CHANGELOG.md" not in names
    assert "README.md" in names

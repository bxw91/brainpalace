"""Tests for Fix 1 — prune Python virtualenvs by the `pyvenv.cfg` marker.

A stdlib venv/virtualenv is definitionally the directory containing
`pyvenv.cfg`; pruning on that marker catches any venv directory name
(`.venv312`, `.venv-py312`, `env`, `myenv`, ...), not just `.venv`/`venv`.
"""

from pathlib import Path

from brainpalace_server.indexing.document_loader import DocumentLoader


def test_venv_marker_prunes_arbitrarily_named_venv_dir(tmp_path: Path) -> None:
    """A dir containing pyvenv.cfg is pruned regardless of its name."""
    (tmp_path / "doc.md").write_text("# real doc\n")
    venv = tmp_path / ".venv312"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    site_pkgs = venv / "lib" / "site-packages" / "somepkg"
    site_pkgs.mkdir(parents=True)
    (site_pkgs / "module.py").write_text("# vendored\n")

    loader = DocumentLoader()
    files = loader.get_supported_files(str(tmp_path))
    names = {f.name for f in files}
    assert "doc.md" in names
    assert "module.py" not in names
    assert not any(".venv312" in str(f) for f in files)


def test_non_venv_dir_with_similar_name_not_pruned(tmp_path: Path) -> None:
    """A dir merely named `venvish` (no pyvenv.cfg) is NOT pruned."""
    (tmp_path / "doc.md").write_text("# real doc\n")
    venvish = tmp_path / "venvish"
    venvish.mkdir()
    (venvish / "notes.md").write_text("# not a venv\n")

    loader = DocumentLoader()
    files = loader.get_supported_files(str(tmp_path))
    names = {f.name for f in files}
    assert "doc.md" in names
    assert "notes.md" in names


def test_arbitrary_named_env_dir_pruned(tmp_path: Path) -> None:
    """`env/` (a common stdlib venv name) is pruned via the pyvenv.cfg marker."""
    (tmp_path / "doc.md").write_text("# real doc\n")
    env = tmp_path / "env"
    env.mkdir()
    (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (env / "readme.md").write_text("# should not be indexed\n")

    loader = DocumentLoader()
    files = loader.get_supported_files(str(tmp_path))
    names = {f.name for f in files}
    assert "doc.md" in names
    assert "readme.md" not in names

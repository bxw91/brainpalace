"""resolve_project_root_with_strategy must only honor an *initialized*
.brainpalace/ in step 1; a bare scaffold must fall through to the outer
initialized project.
"""

from __future__ import annotations

from pathlib import Path

from brainpalace_cli.config import resolve_project_root_with_strategy


def test_scaffold_only_nested_resolves_to_outer_project(tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub = root / "pkg"
    sub.mkdir(parents=True)
    (root / ".brainpalace").mkdir()
    (root / ".brainpalace" / "config.yaml").write_text("api: {}\n")
    (sub / ".brainpalace").mkdir()
    (sub / ".brainpalace" / "data").mkdir()  # scaffold only
    root_resolved, strategy = resolve_project_root_with_strategy(sub)
    assert root_resolved == root
    assert strategy == "brainpalace_dir"


def test_initialized_nested_is_honored(tmp_path: Path) -> None:
    root = tmp_path / "root"
    sub = root / "pkg"
    sub.mkdir(parents=True)
    (sub / ".brainpalace").mkdir()
    (sub / ".brainpalace" / "config.yaml").write_text("api: {}\n")
    resolved, strategy = resolve_project_root_with_strategy(sub)
    assert resolved == sub
    assert strategy == "brainpalace_dir"

"""Discovery must only treat an *initialized* .brainpalace as a project root.

A bare scaffold (data/ dirs but no config.yaml / runtime.json) created as a
side effect in a monorepo sub-package must be skipped so discovery keeps
walking up to the real project / git root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_cli.discovery import discover_project_dir


def _mk_state(
    dir: Path,
    *,
    config: bool = False,
    runtime: bool = False,
    scaffold_only: bool = False,
) -> None:
    sd = dir / ".brainpalace"
    sd.mkdir(parents=True, exist_ok=True)
    if scaffold_only:
        (sd / "data").mkdir(exist_ok=True)  # uninitialized scaffold, no markers
    if config:
        (sd / "config.yaml").write_text("api: {}\n")
    if runtime:
        (sd / "runtime.json").write_text("{}")


def test_initialized_config_is_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))  # keep walk-up within tmp
    proj = tmp_path / "proj"
    proj.mkdir()
    _mk_state(proj, config=True)
    assert discover_project_dir(proj) == proj.resolve()


def test_scaffold_only_is_skipped_walks_up_to_real_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "root"
    sub = root / "sub"
    sub.mkdir(parents=True)
    _mk_state(root, config=True)  # real project
    _mk_state(sub, scaffold_only=True)  # stray scaffold — must be ignored
    assert discover_project_dir(sub) == root.resolve()


def test_runtime_only_is_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    proj.mkdir()
    _mk_state(proj, runtime=True)
    assert discover_project_dir(proj) == proj.resolve()


def test_config_json_only_is_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    proj.mkdir()
    sd = proj / ".brainpalace"
    sd.mkdir()
    (sd / "config.json").write_text("{}")
    assert discover_project_dir(proj) == proj.resolve()

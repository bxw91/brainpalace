"""Regression tests for the unified resolver (issues #124, #128) and doctor."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.doctor import doctor_command
from brainpalace_cli.config import (
    resolve_project_root,
    resolve_project_root_with_strategy,
)
from brainpalace_cli.diagnostics import (
    SEVERITY_OK,
    SEVERITY_WARN,
    _check_collection_sizes,
    _check_graph_size,
    _check_index_staleness,
    _check_version,
    _newest_source_mtime,
    apply_safe_fixes,
    doctor_hint_message,
    run_doctor,
)


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run each test in an isolated cwd with no environment overrides.

    Also redirects ``$HOME`` and ``$XDG_CONFIG_HOME`` at ``tmp_path`` so the
    provider-config loader can't fall back to the developer's real
    ``~/.brainpalace/config.yaml`` or ``~/.config/brainpalace/`` — those would
    emit a "Using legacy config path" warning that contaminates the doctor
    ``--json`` stream.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BRAINPALACE_URL", raising=False)
    monkeypatch.delenv("BRAINPALACE_STATE_DIR", raising=False)
    monkeypatch.delenv("BRAINPALACE_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path


def test_resolve_project_root_prefers_local_state_dir(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nested ``.brainpalace/`` must win over the git top-level (#124, #128).

    Simulates a mono-repo with the git root one level above a sub-project
    that has its own ``.brainpalace/``. Before the fix the CLI walked to
    the git root and missed the local state dir.
    """
    nested = isolated_cwd / "projects" / "app"
    nested.mkdir(parents=True)
    (nested / ".brainpalace").mkdir()

    # Patch git so it pretends ``isolated_cwd`` (the parent) is the repo top.
    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=str(isolated_cwd) + "\n", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)

    assert resolve_project_root(nested) == nested


def test_resolve_project_root_falls_back_to_git_root(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no nested .brainpalace/ exists, fall through to the git root."""
    nested = isolated_cwd / "src"
    nested.mkdir()

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=str(isolated_cwd) + "\n", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)

    assert resolve_project_root(nested) == isolated_cwd


def test_resolve_project_root_no_git_no_state(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No state dir and no git → fall back to the start path."""

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr="not a repo"
        )

    monkeypatch.setattr("subprocess.run", fake_git)
    assert resolve_project_root(isolated_cwd) == isolated_cwd


def test_doctor_hint_when_runtime_missing(isolated_cwd: Path) -> None:
    """Hint message must point at the missing runtime.json, not a generic tip."""
    msg = doctor_hint_message(isolated_cwd)
    assert "runtime.json" in msg
    assert "brainpalace init" in msg


def test_doctor_hint_when_runtime_present(isolated_cwd: Path) -> None:
    """When runtime.json exists, the hint is the generic one."""
    state = isolated_cwd / ".brainpalace"
    state.mkdir()
    (state / "runtime.json").write_text("{}")

    msg = doctor_hint_message(isolated_cwd)
    assert "brainpalace doctor" in msg
    assert "runtime.json" not in msg


def test_run_doctor_uninitialized_project(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Doctor returns non-zero and a project_initialized FAIL on a clean dir."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Pretend cwd is not in a git repo so resolver returns cwd verbatim.
    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)

    report = run_doctor()
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["project_initialized"] == "fail"
    assert report.exit_code == 1


def test_doctor_command_emits_json(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json output must be parseable and include exit_code."""

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    runner = CliRunner()
    result = runner.invoke(doctor_command, ["--json"])

    # Doctor exits non-zero on fresh dirs but still emits a JSON body first.
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "checks" in payload
    assert payload["exit_code"] == 1
    assert any(c["name"] == "python_version" for c in payload["checks"])


# --------------------------------------------------------------------------- #
# Issue #146 — doctor enhancements (--fix, --version check, project-root
# strategy explanation, langextract dep check).
# --------------------------------------------------------------------------- #


def test_check_version_reports_installed_cli_version() -> None:
    """Regression for #146 check #2 — version check should resolve cleanly."""
    result = _check_version()
    # We can't assert the exact version (varies per release) but it must be OK
    # and the message must include the package name.
    assert result.status == "ok"
    assert "brainpalace-cli" in result.message
    assert "version" in result.details


def test_resolve_project_root_with_strategy_returns_label(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#146 check #3 — resolver must report *which* rule matched."""
    (isolated_cwd / ".brainpalace").mkdir()

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=str(isolated_cwd) + "\n", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)

    root, strategy = resolve_project_root_with_strategy(isolated_cwd)
    assert root == isolated_cwd
    assert strategy == "brainpalace_dir"


def test_doctor_project_init_message_includes_strategy(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The project_initialized check should explain *why* the dir was picked."""

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    report = run_doctor()
    proj_check = next(c for c in report.checks if c.name == "project_initialized")
    # cwd_fallback strategy because no markers exist in the tmp dir.
    assert "no markers found" in proj_check.message
    assert proj_check.details.get("resolved_via") == "cwd_fallback"


def test_apply_safe_fixes_adds_gitignore_entry(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#146 --fix layer A — append .brainpalace/ to .gitignore (safe, idempotent)."""

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    report = run_doctor()
    actions = apply_safe_fixes(report)

    gi = isolated_cwd / ".gitignore"
    assert gi.exists()
    assert ".brainpalace/" in gi.read_text()
    assert any("gitignore" in a.lower() for a in actions)


def test_doctor_fix_flag_creates_state_dir(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--fix end-to-end: stub config.json gets created when project not initialized."""

    def fake_git(args, *_, **__):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_git)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    runner = CliRunner()
    result = runner.invoke(doctor_command, ["--json", "--fix"])
    payload = json.loads(result.output)

    assert "applied_fixes" in payload
    # State dir created → fix actions should mention either config.json or
    # gitignore (both apply on a clean tmp dir).
    assert payload["applied_fixes"], "expected at least one safe fix action"
    assert (isolated_cwd / ".brainpalace" / "config.json").exists()


# ---------------------------------------------------------------------------
# Phase 040 — doctor scale checks
# ---------------------------------------------------------------------------


def _status(**graph: object) -> dict:
    """Build a minimal /health/status payload for scale-check tests."""
    payload: dict = {
        "total_code_chunks": 120,
        "total_doc_chunks": 30,
        "last_indexed_at": None,
        "graph_index": None,
    }
    if graph:
        payload["graph_index"] = dict(graph)
    return payload


# --- graph_size -----------------------------------------------------------


def test_check_graph_size_warns_over_threshold() -> None:
    payload = _status(
        enabled=True, initialized=True, store_type="simple",
        entity_count=20000, relationship_count=20000,
    )
    res = _check_graph_size(payload, max_nodes=25000)
    assert res.status == SEVERITY_WARN
    assert res.details["nodes"] == 40000
    assert "090" in (res.fix or "")


def test_check_graph_size_ok_under_threshold() -> None:
    payload = _status(
        enabled=True, store_type="simple",
        entity_count=10, relationship_count=5,
    )
    res = _check_graph_size(payload, max_nodes=25000)
    assert res.status == SEVERITY_OK
    assert res.details["nodes"] == 15


def test_check_graph_size_skips_on_persistent_backend() -> None:
    # store_type != "simple" → Phase 090 active → check auto-clears.
    payload = _status(
        enabled=True, store_type="sqlite",
        entity_count=99999, relationship_count=99999,
    )
    res = _check_graph_size(payload, max_nodes=25000)
    assert res.status == SEVERITY_OK


def test_check_graph_size_skips_when_disabled_or_no_payload() -> None:
    assert _check_graph_size(None, max_nodes=25000).status == SEVERITY_OK
    assert _check_graph_size(_status(), max_nodes=25000).status == SEVERITY_OK


# --- index_staleness ------------------------------------------------------


def test_check_index_staleness_warns_when_tree_newer(tmp_path: Path) -> None:
    import time

    f = tmp_path / "src.py"
    f.write_text("x = 1\n")
    now = time.time()
    # File is "now"; index ran 30 days ago.
    indexed = now - 30 * 86400
    from datetime import datetime, timezone

    payload = _status()
    payload["last_indexed_at"] = datetime.fromtimestamp(
        indexed, tz=timezone.utc
    ).isoformat()
    res = _check_index_staleness(tmp_path, payload, max_days=7)
    assert res.status == SEVERITY_WARN
    assert "index" in res.message.lower()


def test_check_index_staleness_ok_when_fresh(tmp_path: Path) -> None:
    import time
    from datetime import datetime, timezone

    f = tmp_path / "src.py"
    f.write_text("x = 1\n")
    # Index ran "now" → tree not newer.
    payload = _status()
    payload["last_indexed_at"] = datetime.fromtimestamp(
        time.time() + 60, tz=timezone.utc
    ).isoformat()
    res = _check_index_staleness(tmp_path, payload, max_days=7)
    assert res.status == SEVERITY_OK


def test_check_index_staleness_skips_when_never_indexed(tmp_path: Path) -> None:
    res = _check_index_staleness(tmp_path, _status(), max_days=7)
    assert res.status == SEVERITY_OK


def test_newest_source_mtime_skips_heavy_dirs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "junk").write_text("x")
    (tmp_path / "real.py").write_text("y")
    mtime = _newest_source_mtime(tmp_path)
    assert mtime is not None


# --- collection_sizes -----------------------------------------------------


def test_check_collection_sizes_reports_counts() -> None:
    payload = _status(enabled=True, store_type="simple")
    payload["session_chunks"] = 9  # Phase 050 feeds this
    res = _check_collection_sizes(payload, memory_count=7)
    assert res.status == SEVERITY_OK
    assert res.details["code"] == 120
    assert res.details["docs"] == 30
    assert res.details["memories"] == 7
    assert res.details["sessions"] == 9
    assert "code=120" in res.message
    assert "sessions=9" in res.message


def test_check_collection_sizes_skips_when_server_down() -> None:
    res = _check_collection_sizes(None, memory_count=None)
    assert res.status == SEVERITY_OK
    assert "unavailable" in res.message.lower()

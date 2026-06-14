#!/usr/bin/env python3
"""lint:doc-sync — interface docs stay in sync with live code (CLI surface).

Pinned to the REPO code (run via the cli Poetry env), never a stale global binary
(resolution A). `--mode warn` reports without failing; `--mode block` fails on drift.
See docs/superpowers/specs/2026-06-13-interface-doc-sync-design.md."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "brainpalace-cli"))

from brainpalace_cli.doc_sync import SCHEMA_VERSION  # noqa: E402
from brainpalace_cli.doc_sync.checkers import cli_commands  # noqa: E402
from brainpalace_cli.doc_sync.introspect import live_snapshot  # noqa: E402
from brainpalace_cli.doc_sync.orchestrator import render_report, run_check  # noqa: E402

CliCommandsChecker = cli_commands.CliCommandsChecker

_DOCS = REPO / "brainpalace-plugin" / "commands"


def assert_schema_version(dumped: dict) -> None:
    got = dumped.get("schema_version")
    if got != SCHEMA_VERSION:
        print(
            f"doc-sync FAILED: dump schema_version={got} != checker {SCHEMA_VERSION} "
            "(dumper/checker contract skew — rebuild the repo env)."
        )
        raise SystemExit(1)


def _clean_env() -> dict:
    """Drop the parent virtualenv markers so a nested ``poetry run`` resolves each
    project's OWN env (mirrors the Taskfile running each gate as a fresh task)."""
    env = dict(os.environ)
    for var in ("VIRTUAL_ENV", "POETRY_ACTIVE"):
        env.pop(var, None)
    return env


def run_wrapped_gates() -> int:
    """Invoke the existing ai-guidance + dashboard parity gates (wrap, don't rewrite).
    Returns 0 iff both pass; prints their output under the doc-sync report on failure."""
    rc = 0
    env = _clean_env()
    ai = subprocess.run(
        ["poetry", "run", "python", str(REPO / "scripts" / "check_ai_guidance_parity.py")],
        cwd=REPO / "brainpalace-cli",
        capture_output=True,
        text=True,
        env=env,
    )
    if ai.returncode != 0:
        print("wrapped gate ai-guidance-parity FAILED:\n" + ai.stdout + ai.stderr)
        rc = 1
    # Dashboard parity is a local-only gate: it needs the dashboard's own
    # (Python 3.12) venv, which `task before-push` installs but the publish /
    # PR-QA CI jobs (server+cli, 3.11) deliberately do not. Skip when that env
    # is absent so wrapping it here doesn't drag a local-only gate into CI;
    # before-push always has the venv, so it still runs there.
    # BRAINPALACE_DOCSYNC_NO_DASHBOARD forces the skip so `task release:rehearse-ci`
    # can reproduce the dashboard-absent CI gate locally.
    dashboard_env = (REPO / "brainpalace-dashboard" / ".venv").exists()
    if dashboard_env and not os.environ.get("BRAINPALACE_DOCSYNC_NO_DASHBOARD"):
        dash = subprocess.run(
            ["poetry", "run", "pytest", "tests/test_dashboard_parity.py", "-q"],
            cwd=REPO / "brainpalace-dashboard",
            capture_output=True,
            text=True,
            env=env,
        )
        if dash.returncode != 0:
            print("wrapped gate dashboard-parity FAILED:\n" + dash.stdout + dash.stderr)
            rc = 1
    else:
        print(
            "wrapped gate dashboard-parity SKIPPED "
            "(dashboard env not installed — local-only gate, runs in `task before-push`)."
        )
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["warn", "block"], default="block")
    args = ap.parse_args()

    snap = live_snapshot()
    assert_schema_version({"schema_version": snap.schema_version})
    code, records = run_check([CliCommandsChecker(docs_dir=_DOCS)], snap)
    print(render_report(records))
    gates_rc = run_wrapped_gates()
    if args.mode == "warn":
        return 0
    return code or gates_rc


if __name__ == "__main__":
    raise SystemExit(main())

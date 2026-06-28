"""The plugin hook shims must fail SOFT under version skew.

If `brainpalace` is on PATH but too old to have the `hook` command group (a real
scenario when the plugin is newer than the installed CLI), invoking it errors
like Click's "No such command 'hook'." For a UserPromptSubmit / PreToolUse hook
that surfaced error BLOCKS the prompt. The shim must therefore swallow a failing
`brainpalace hook ...` and exit 0 — never block, never leak stderr.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_BASH = shutil.which("bash") or "/bin/bash"
_REPO = Path(__file__).resolve().parents[2]
_SHIMS = [
    _REPO / "brainpalace-plugin/hooks/sessionstart-hook.sh",
    _REPO / "brainpalace-plugin/hooks/userpromptsubmit-drain-hook.sh",
    _REPO / "brainpalace-plugin/hooks/pretooluse-subagent-guard-hook.sh",
]


def _write_stub(bindir: Path, body: str) -> None:
    p = bindir / "brainpalace"
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_shim(shim: Path, path_value: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PATH=path_value)
    return subprocess.run(
        [_BASH, str(shim)], input="{}", text=True, capture_output=True, env=env
    )


@pytest.mark.parametrize("shim", _SHIMS, ids=lambda s: s.name)
def test_shim_failsoft_when_hook_command_missing(shim: Path, tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # A too-old CLI: `brainpalace hook ...` errors to stderr and exits non-zero.
    _write_stub(bindir, "echo \"Error: No such command 'hook'.\" >&2\nexit 2")
    res = _run_shim(shim, f"{bindir}:{os.environ['PATH']}")
    assert (
        res.returncode == 0
    ), f"{shim.name} blocked the session (rc={res.returncode}, stderr={res.stderr!r})"
    assert res.stderr.strip() == "", f"{shim.name} leaked stderr: {res.stderr!r}"


@pytest.mark.parametrize("shim", _SHIMS, ids=lambda s: s.name)
def test_shim_noop_when_brainpalace_absent(shim: Path, tmp_path: Path) -> None:
    # Not on PATH at all → never block, never leak stderr.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    res = _run_shim(shim, str(bindir))
    assert res.returncode == 0
    assert res.stderr.strip() == ""
    if shim.name == "sessionstart-hook.sh":
        # The sessionstart shim is the ONE exception: an absent CLI cannot
        # announce itself, so the shim emits a single install directive that
        # asks the model to offer installation. Must be valid JSON.
        payload = json.loads(res.stdout)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert "AskUserQuestion" in ctx
        assert "/brainpalace-install" in ctx or "/brainpalace-setup" in ctx
    else:
        # Every other shim stays strictly silent when the CLI is absent.
        assert res.stdout.strip() == ""

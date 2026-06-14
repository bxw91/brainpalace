"""The CI-rehearsal sitecustomize must block `brainpalace_dashboard` only when
BRAINPALACE_BLOCK_DASHBOARD=1, so `task release:rehearse-ci` reproduces the
dashboard-absent publish gate on a dev box that has the dashboard installed."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BLOCKER_DIR = REPO / "scripts" / "ci_rehearsal"


def _run(code: str, env_flag: str | None) -> subprocess.CompletedProcess:
    env = {"PYTHONPATH": str(BLOCKER_DIR), "PATH": "/usr/bin:/bin"}
    if env_flag is not None:
        env["BRAINPALACE_BLOCK_DASHBOARD"] = env_flag
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )


def test_blocker_raises_when_flag_set():
    r = _run("import brainpalace_dashboard", "1")
    assert r.returncode != 0
    assert "blocked by CI rehearsal" in r.stderr


def test_blocker_inert_without_flag():
    code = (
        "import sys; "
        "print(any(type(f).__name__ == '_DashboardBlocker' for f in sys.meta_path))"
    )
    assert _run(code, None).stdout.strip() == "False"
    assert _run(code, "0").stdout.strip() == "False"

import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[3] / "scripts" / "githooks" / "pre-commit"


def test_hook_skips_during_rebase(tmp_path):
    # Simulate a rebase-in-progress by faking the git dir marker.
    fake_git = tmp_path / ".git"
    (fake_git / "rebase-merge").mkdir(parents=True)
    env = {**os.environ, "GIT_DIR": str(fake_git)}
    proc = subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0
    assert "skip" in (proc.stdout + proc.stderr).lower()

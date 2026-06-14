import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_lint_entrypoint_runs_and_pins_version():
    # Runs the real entrypoint; exit code 0/1 (drift), never a crash/traceback.
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_doc_sync.py"), "--mode", "warn"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0  # warn mode never fails the build
    assert "doc-sync" in (proc.stdout + proc.stderr)

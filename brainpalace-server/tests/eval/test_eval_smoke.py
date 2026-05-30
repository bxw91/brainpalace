"""End-to-end smoke test for the eval harness.

Asserts the harness wires together (index → query → score) on a single bm25
case, so it can't silently rot.

Two things make an *in-process* live test impossible here: (1) the shared
``tests/conftest.py`` force-sets ``OPENAI_API_KEY=test-key`` for the whole suite
before any app import, and (2) providers are cached as singletons once built, so
a late ``os.environ`` override never reaches the embedding client. We therefore
run the harness in a **subprocess** with a clean, real-keyed environment —
immune to both — and only when opted in via ``BRAINPALACE_EVAL_OPENAI_KEY``.
``pr-qa-gate`` never sets that var, so the gate stays green and key-free.

Run the live smoke with:

    BRAINPALACE_EVAL_OPENAI_KEY="$OPENAI_API_KEY" \
        env -u VIRTUAL_ENV poetry run pytest tests/eval/test_eval_smoke.py

The scorer's logic is covered key-free in ``test_scorer.py``; this adds the
integration wiring whenever a real key is supplied.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_LIVE_KEY = os.getenv("BRAINPALACE_EVAL_OPENAI_KEY")
_SERVER_DIR = Path(__file__).resolve().parents[2]  # brainpalace-server/

pytestmark = pytest.mark.skipif(
    not _LIVE_KEY,
    reason="set BRAINPALACE_EVAL_OPENAI_KEY to a real key to run the live eval smoke",
)


def test_harness_runs_one_bm25_case_end_to_end():
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = _LIVE_KEY  # type: ignore[assignment]
    env.pop("VIRTUAL_ENV", None)

    proc = subprocess.run(
        [sys.executable, "-m", "tests.eval.runner", "--one", "bm25-retry-after"],
        cwd=_SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert proc.returncode == 0, f"runner failed:\n{proc.stdout}\n{proc.stderr}"
    # The case is a clear keyword hit; its expected file must appear, with no
    # error marker on the case line.
    assert "rate_limiting.md" in proc.stdout, proc.stdout
    assert "[ERR]" not in proc.stdout, proc.stdout

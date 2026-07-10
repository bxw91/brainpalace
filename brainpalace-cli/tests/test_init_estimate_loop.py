"""Tests for the up-front pre-index token-estimate loop + breakdown rendering."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from rich.console import Console

from brainpalace_cli.commands.estimate_util import print_token_estimate
from brainpalace_cli.commands.init import _estimate_and_confirm_local


def _ok() -> dict[str, object]:
    return {
        "status": "ok",
        "stdout": json.dumps(
            {
                "files": 5,
                "code_files": 3,
                "doc_files": 2,
                "total_bytes": 100,
                "raw_tokens": 100,
                "est_embedding_tokens": 110,
                "overlap_factor": 1.1,
                "tokenizer": "heuristic(chars/4)",
                "embedding_provider": "ollama",
                "embedding_model": "x",
                "approximate": True,
            }
        ),
    }


def _est_dict() -> dict[str, object]:
    return json.loads(_ok()["stdout"])


def test_proceed_keeps_scope_and_estimates_with_include_code():
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_est_dict()),
        ) as es,
        patch("brainpalace_cli.commands.init.click.prompt", return_value="proceed"),
    ):
        out = _estimate_and_confirm_local([Path("/p")], Path("/p/config.yaml"), True)
    assert out is True
    assert es.call_count == 1
    assert es.call_args.kwargs["include_code"] is True


def test_cancel_returns_none():
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_est_dict()),
        ),
        patch("brainpalace_cli.commands.init.click.prompt", return_value="cancel"),
    ):
        assert (
            _estimate_and_confirm_local([Path("/p")], Path("/p/c.yaml"), True) is None
        )


def test_change_then_proceed_flips_scope_and_reestimates():
    prompts = iter(["change", "proceed"])
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_est_dict()),
        ) as es,
        patch(
            "brainpalace_cli.commands.init.click.prompt",
            side_effect=lambda *a, **k: next(prompts),
        ),
    ):
        out = _estimate_and_confirm_local([Path("/p")], Path("/p/c.yaml"), True)
    assert out is False  # changed scope → code off
    assert es.call_count == 2  # re-estimated after change
    include_flags = [c.kwargs["include_code"] for c in es.call_args_list]
    assert include_flags == [True, False]


# ---------------------------------------------------------------------------
# Phase 4 — breakdown line rendered when git/session tokens present
# ---------------------------------------------------------------------------


def _capture(est: dict) -> str:
    """Render print_token_estimate into a plain string (markup processed, no colour)."""
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, no_color=True)
    print_token_estimate(console, est)
    return buf.getvalue()


def test_breakdown_shown_when_git_tokens_present():
    est = {
        **json.loads(_ok()["stdout"]),
        "doc_tokens": 100,
        "git_tokens": 500,
        "git_commits": 42,
        "session_tokens": 0,
        "session_files": 0,
        "est_embedding_tokens": 600,
    }
    output = _capture(est)
    # Rendered text: markup processed, colours stripped — labels appear as plain words.
    assert "git" in output
    assert "42" in output  # commit count rendered
    assert "500" in output  # git token count rendered
    assert "docs" in output  # docs segment always present in breakdown


def test_breakdown_hidden_when_git_tokens_zero():
    est = {
        **json.loads(_ok()["stdout"]),
        "doc_tokens": 110,
        "git_tokens": 0,
        "git_commits": 0,
        "session_tokens": 0,
        "session_files": 0,
        "est_embedding_tokens": 110,
    }
    output = _capture(est)
    # Breakdown line should NOT appear when both git and session are zero.
    assert "git" not in output


def test_breakdown_shown_when_session_tokens_present():
    est = {
        **json.loads(_ok()["stdout"]),
        "doc_tokens": 100,
        "git_tokens": 0,
        "git_commits": 0,
        "session_tokens": 200,
        "session_files": 3,
        "est_embedding_tokens": 300,
    }
    output = _capture(est)
    assert "sessions" in output
    assert "200" in output  # session token count rendered
    assert "docs" in output  # docs segment always present in breakdown
    # Fix 5: git segment must be absent when git_tokens==0 but session_tokens>0
    assert "git" not in output

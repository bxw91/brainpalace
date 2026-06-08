"""Tests for the interactive pre-index token-estimate loop (_estimate_loop)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from brainpalace_cli.commands.init import _estimate_loop


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
                "summaries_enabled": False,
                "approximate": True,
            }
        ),
    }


def test_proceed_keeps_scope_and_estimates_with_include_code():
    with (
        patch(
            "brainpalace_cli.commands.init._run_subcommand", return_value=_ok()
        ) as rs,
        patch("brainpalace_cli.commands.init.click.prompt", return_value="proceed"),
    ):
        out = _estimate_loop(Path("/p"), True)
    assert out is True
    assert rs.call_count == 1
    argv = rs.call_args[0][0]
    assert "--estimate" in argv and "--include-code" in argv


def test_skip_returns_none():
    with (
        patch("brainpalace_cli.commands.init._run_subcommand", return_value=_ok()),
        patch("brainpalace_cli.commands.init.click.prompt", return_value="skip"),
    ):
        assert _estimate_loop(Path("/p"), True) is None


def test_toggle_then_proceed_flips_scope_and_reestimates():
    prompts = iter(["toggle", "proceed"])
    with (
        patch(
            "brainpalace_cli.commands.init._run_subcommand", return_value=_ok()
        ) as rs,
        patch(
            "brainpalace_cli.commands.init.click.prompt",
            side_effect=lambda *a, **k: next(prompts),
        ),
    ):
        out = _estimate_loop(Path("/p"), True)
    assert out is False  # toggled off code
    assert rs.call_count == 2  # re-estimated after toggle
    flags = [c[0][0] for c in rs.call_args_list]
    assert any("--include-code" in f for f in flags)
    assert any("--no-code" in f for f in flags)

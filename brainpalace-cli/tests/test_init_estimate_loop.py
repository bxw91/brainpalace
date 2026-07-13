"""Tests for the up-front pre-index token-estimate loop + breakdown rendering."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml
from rich.console import Console

from brainpalace_cli.commands.estimate_util import (
    print_folder_estimate,
    print_token_estimate,
)
from brainpalace_cli.commands.init import (
    _estimate_and_confirm_local,
    _gitignore_remove_line,
    _normalize_exclude_input,
    _read_project_excludes,
    _write_project_excludes,
)


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


def _folder_est_files(n_files: int) -> dict:
    return {
        "files": n_files,
        "tokenizer": "heuristic",
        "by_folder": (
            [{"name": "pkg", "files": n_files, "code_tokens": 10, "doc_tokens": 0}]
            if n_files
            else []
        ),
    }


def test_menu_proceed_returns_include_code(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("{}\n")
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_folder_est_files(3)),
        ),
        patch("brainpalace_cli.commands.init.click.prompt", return_value="5"),
    ):
        out = _estimate_and_confirm_local(
            [tmp_path],
            tmp_path / "config.yaml",
            True,
            interactive=True,
            state_dir=tmp_path,
            project_root=tmp_path,
        )
    assert out is True


def test_menu_cancel_returns_none(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("{}\n")
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_folder_est_files(3)),
        ),
        patch("brainpalace_cli.commands.init.click.prompt", return_value="6"),
    ):
        out = _estimate_and_confirm_local(
            [tmp_path],
            tmp_path / "config.yaml",
            True,
            interactive=True,
            state_dir=tmp_path,
            project_root=tmp_path,
        )
    assert out is None


def test_menu_add_config_then_reestimate(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("{}\n")
    (tmp_path / "e2e").mkdir()
    prompts = iter(["1", "e2e", "b", "4", "5"])
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_folder_est_files(3)),
        ),
        patch(
            "brainpalace_cli.commands.init.click.prompt",
            side_effect=lambda *a, **k: next(prompts),
        ),
    ):
        out = _estimate_and_confirm_local(
            [tmp_path],
            tmp_path / "config.yaml",
            True,
            interactive=True,
            state_dir=tmp_path,
            project_root=tmp_path,
        )
    assert out is True
    assert _read_project_excludes(tmp_path) == ["**/e2e/**"]


def test_menu_add_gitignore_stays_on_cancel(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("{}\n")
    prompts = iter(["1", "scratch/", "g", "6"])
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_folder_est_files(3)),
        ),
        patch(
            "brainpalace_cli.commands.init.click.prompt",
            side_effect=lambda *a, **k: next(prompts),
        ),
    ):
        out = _estimate_and_confirm_local(
            [tmp_path],
            tmp_path / "config.yaml",
            True,
            interactive=True,
            state_dir=tmp_path,
            project_root=tmp_path,
        )
    assert out is None
    assert "scratch/" in (tmp_path / ".gitignore").read_text()  # stays on cancel


def test_menu_empty_state_blocks_proceed(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("{}\n")
    # First proceed (5) is blocked (0 files) → then cancel (6).
    prompts = iter(["5", "6"])
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_folder_est_files(0)),
        ),
        patch(
            "brainpalace_cli.commands.init.click.prompt",
            side_effect=lambda *a, **k: next(prompts),
        ),
    ):
        out = _estimate_and_confirm_local(
            [tmp_path],
            tmp_path / "config.yaml",
            True,
            interactive=True,
            state_dir=tmp_path,
            project_root=tmp_path,
        )
    assert out is None


def test_noninteractive_prints_once_no_menu(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("{}\n")
    with (
        patch(
            "brainpalace_server.services.estimate.estimate_tokens_local",
            new=AsyncMock(return_value=_folder_est_files(3)),
        ),
        patch("brainpalace_cli.commands.init.click.prompt") as pr,
    ):
        out = _estimate_and_confirm_local(
            [tmp_path],
            tmp_path / "config.yaml",
            True,
            interactive=False,
            state_dir=tmp_path,
            project_root=tmp_path,
        )
    assert out is True
    pr.assert_not_called()  # no menu on non-interactive


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


# ---------------------------------------------------------------------------
# Task 2 — print_folder_estimate renderer
# ---------------------------------------------------------------------------


def _folder_est() -> dict:
    return {
        "files": 3,
        "tokenizer": "tiktoken:cl100k_base",
        "by_folder": [
            {"name": "pkg", "files": 1, "code_tokens": 800, "doc_tokens": 0},
            {"name": "(root files)", "files": 1, "code_tokens": 40, "doc_tokens": 9},
            {"name": "docs", "files": 1, "code_tokens": 0, "doc_tokens": 180},
        ],
    }


def _capture_folder(**kw) -> str:
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, no_color=True, width=100)
    print_folder_estimate(console, _folder_est(), **kw)
    return buf.getvalue()


def test_folder_estimate_alphabetical_root_last_and_total():
    out = _capture_folder(stale=False, bp_excludes=[], session_gitignore=[])
    # docs before pkg (alphabetical); (root files) last
    assert out.index("docs") < out.index("pkg") < out.index("(root files)")
    assert "TOTAL" in out
    assert "overlap-inflated" in out
    assert "cl100k" in out


def test_folder_estimate_stale_and_ignore_lists():
    out = _capture_folder(
        stale=True,
        bp_excludes=["**/e2e/**"],
        session_gitignore=["scratch/"],
    )
    assert "stale" in out
    assert "**/e2e/**" in out
    assert "scratch/" in out


# ---------------------------------------------------------------------------
# Task 3 — exclude-config + gitignore edit helpers
# ---------------------------------------------------------------------------


def test_normalize_dir_file_and_glob(tmp_path: Path):
    (tmp_path / "e2e").mkdir()
    (tmp_path / "note.md").write_text("x")
    assert _normalize_exclude_input("e2e", tmp_path) == "**/e2e/**"
    assert _normalize_exclude_input("note.md", tmp_path) == "**/note.md"
    assert _normalize_exclude_input("*.log", tmp_path) == "*.log"


def test_read_write_reset_excludes(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("indexing: {}\n")
    assert _read_project_excludes(tmp_path) == []
    _write_project_excludes(tmp_path, ["**/e2e/**"])
    assert _read_project_excludes(tmp_path) == ["**/e2e/**"]
    # reset to empty removes the key (sparse)
    _write_project_excludes(tmp_path, None)
    assert _read_project_excludes(tmp_path) == []
    assert "exclude_patterns" not in (
        yaml.safe_load((tmp_path / "config.yaml").read_text()).get("indexing") or {}
    )


def test_gitignore_remove_line(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("keep/\nscratch/\n")
    assert _gitignore_remove_line(tmp_path, "scratch/") is True
    assert "scratch/" not in (tmp_path / ".gitignore").read_text()
    assert "keep/" in (tmp_path / ".gitignore").read_text()
    assert _gitignore_remove_line(tmp_path, "absent/") is False

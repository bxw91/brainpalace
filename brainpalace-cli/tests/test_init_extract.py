"""`init` extract resolution + config writer (Task 2)."""

from __future__ import annotations

import yaml

from brainpalace_cli.commands.init import write_session_config
from brainpalace_cli.commands.init_plan import (
    downgrade_to_config_only,
    format_init_plan,
    resolve_init_plan,
)

_BASE = {
    "start": None,
    "watch": None,
    "no_watch": False,
    "sessions": None,
    "archive": None,
    "extract": None,
    "yes": False,
    "is_tty": False,
}


def _resolve(**kw):
    base = dict(_BASE)
    base.update(kw)
    return resolve_init_plan(**base)


def test_extract_defaults_on_with_consent() -> None:
    assert _resolve(yes=True).extract is True


def test_extract_off_without_consent() -> None:
    assert _resolve().extract is False


def test_explicit_extract_wins_even_in_ci() -> None:
    assert _resolve(extract=True).extract is True
    assert _resolve(yes=True, extract=False).extract is False


def test_downgrade_disables_extract() -> None:
    plan = _resolve(yes=True)
    assert downgrade_to_config_only(plan).extract is False


def test_format_mentions_summarize_when_extract() -> None:
    line = format_init_plan(
        _resolve(yes=True),
        embedding=("openai", "text-embedding-3-large"),
        summarize=("subagent",),
    )
    assert "summarize chat sessions" in line
    assert "→ Claude Code Haiku (subscription)" in line


def test_write_session_config_sets_extract_mode(tmp_path) -> None:
    write_session_config(tmp_path, extract_mode="subagent")
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["session_extraction"]["mode"] == "subagent"


def test_write_session_config_extract_mode_preserves_indexing(tmp_path) -> None:
    write_session_config(tmp_path, index=True, archive=True)
    write_session_config(tmp_path, extract_mode="provider")
    data = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert data["session_extraction"]["mode"] == "provider"
    assert data["session_indexing"]["enabled"] is True

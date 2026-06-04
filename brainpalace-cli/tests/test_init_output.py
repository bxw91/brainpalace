"""Realistic second-part output of `brainpalace init` (_emit_init_result)."""

from __future__ import annotations

from pathlib import Path

from brainpalace_cli.commands.init import _emit_init_result

_STARTED_WATCHED = [
    {"step": "start", "status": "ok"},
    {"step": "watch", "status": "ok"},
]


def _emit(capsys, **kw):
    base = {
        "project_root": Path("/tmp/p"),
        "resolved_state_dir": Path("/tmp/p/.brainpalace"),
        "config_path": Path("/tmp/p/.brainpalace/config.yaml"),
        "config": {},
        "gitignore_added": False,
        "post_init_steps": _STARTED_WATCHED,
        "start_used": True,
        "watch": "auto",
        "json_output": False,
    }
    base.update(kw)
    _emit_init_result(**base)
    # Collapse rich's soft-wrap newlines so phrase assertions don't split.
    return " ".join(capsys.readouterr().out.split())


def test_summaries_subagent_when_plugin_present(capsys):
    out = _emit(capsys, extract_on=True, plugin_present=True)
    assert "Chat summaries:" in out
    assert "Claude Code Haiku" in out
    assert "isn't installed" not in out


def test_summaries_warns_when_plugin_absent(capsys):
    out = _emit(capsys, extract_on=True, plugin_present=False)
    assert "Chat summaries:" in out
    assert "isn't installed" in out
    assert "install-agent" in out


def test_summaries_off_when_extract_off(capsys):
    out = _emit(capsys, extract_on=False, plugin_present=True)
    assert "Chat summaries:" in out
    assert "off" in out
    assert "Claude Code Haiku" not in out


def test_session_embed_note_names_provider(capsys):
    out = _emit(
        capsys,
        sessions_on=True,
        embedding=("openai", "text-embedding-3-large"),
        extract_on=False,
    )
    assert "OpenAI text-embedding-3-large" in out


def test_no_session_embed_note_when_sessions_off(capsys):
    out = _emit(
        capsys, sessions_on=False, embedding=("openai", "text-embedding-3-large")
    )
    assert "text-embedding-3-large" not in out

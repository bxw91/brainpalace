"""`hook` — internal dispatcher invoked by the installed thin-shim hooks.

The hooks written into ``~/.claude/hooks`` are one-line shims
(``exec brainpalace hook <event> ... || true``). ALL logic + text lives here in
the CLI, so a ``pip``/CLI upgrade propagates every change instantly — the
installed shim never goes stale (it contains nothing version-specific). See
CLAUDE.md → "AI-guidance parity" and the thin-shim rationale in the plan.

This command is ``hidden`` (internal plumbing, not a user command) and
dashboard-allowlisted as ``cli_only``.

Hard rule: a hook must NEVER block or crash a session. Every path is fail-soft —
on any error we print nothing on the block channel and exit 0.
"""

from __future__ import annotations

import json

import click

from ..ai_guidance import nudge
from ..discovery import discover_project_dir, discover_server_url


@click.group("hook", hidden=True)
def hook_group() -> None:
    """Internal dispatcher for BrainPalace's Claude Code hooks (not a user command)."""


@hook_group.command("sessionstart")
def hook_sessionstart() -> None:
    """Emit the SessionStart ``additionalContext`` block for an indexed project.

    Mirrors the legacy ``sessionstart-hook.sh``:
      - no ``.brainpalace/`` in CWD/ancestors  → emit nothing (do not force
        BrainPalace on non-indexed projects);
      - indexed + server up                    → NUDGE + frozen context snapshot;
      - indexed + server down                  → NUDGE only (tells the AI the
        project IS indexed, so it should start the server, not fall back to grep).
    """
    try:
        _emit_sessionstart()
    except Exception:
        # Never block session start. Swallow everything.
        pass


def _emit_sessionstart() -> None:
    project = discover_project_dir(None)
    if project is None:
        return  # whoami exit-1 equivalent: silent no-op for non-indexed projects.

    msg = nudge()
    if not msg:
        return  # bundled guidance unavailable → fail soft, emit nothing.

    url = discover_server_url(None)
    if url:
        # Server up: append the frozen-snapshot context block (project facts +
        # curated memory). Fail soft — a context error must not drop the NUDGE.
        context = _session_context(url)
        if context.strip():
            msg += "\n\n" + context.strip()

    click.echo(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": msg,
                }
            }
        )
    )


def _session_context(url: str) -> str:
    """Fetch the session-context text block; return ``""`` on any failure."""
    try:
        from ..client import DocServeClient

        with DocServeClient(base_url=url) as client:
            data = client.session_context()
        return str(data.get("text", "")) if isinstance(data, dict) else ""
    except Exception:
        return ""

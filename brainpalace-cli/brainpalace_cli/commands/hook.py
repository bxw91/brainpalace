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
import os
import re
import sys
from pathlib import Path
from typing import Any

import click

from ..ai_guidance import nudge
from ..discovery import discover_project_dir, discover_server_url
from ..doc_sync.triggers import is_interface_source
from ..xdg_paths import get_xdg_config_dir

_DOCSYNC_NUDGE = (
    "Interface source changed — run `brainpalace sync-docs --fix` and commit the "
    "regenerated docs before finishing."
)


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


@hook_group.command("posttooluse")
def hook_posttooluse() -> None:
    """Advisory nudge when an interface-source file is edited. Never blocks."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        path = (payload.get("tool_input") or {}).get("file_path", "")
        if path and is_interface_source(path):
            click.echo(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": _DOCSYNC_NUDGE,
                        }
                    }
                )
            )
    except Exception:  # noqa: BLE001 — a hook must NEVER crash/block a session
        pass


# --- subagent guard (PreToolUse) ------------------------------------------

# Query modes a guarded subagent prompt must reference to prove it will search
# via BrainPalace. Mirrors the modes accepted by `brainpalace query --mode`.
_GUARD_QUERY_MODES = ("hybrid", "bm25", "vector", "graph", "multi")
_GUARD_DIRECTIVE_RE = re.compile(
    r"brainpalace\s+query\s+.*--mode\s+(?:" + "|".join(_GUARD_QUERY_MODES) + r")",
    re.IGNORECASE,
)
_GUARD_BYPASS_RE = re.compile(
    r"(do not|don.t|never)\s+(use|invoke|call|run)\s+.{0,40}brainpalace",
    re.IGNORECASE,
)
_GUARD_EXEMPT_RE = re.compile(r"^#\s*BRAINPALACE_EXEMPT:\s*(.+)$")
_GUARD_DENY_REASON = (
    "Subagent prompt must instruct BrainPalace search: include "
    "`brainpalace query ... --mode <hybrid|bm25|vector|graph|multi>`. "
    "If genuinely exempt, open the prompt with a line "
    "`# BRAINPALACE_EXEMPT: <reason of 20+ chars>`."
)
_GUARD_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "enforce",
    # The shipped brainpalace research agent is BrainPalace-only by construction
    # (Glob/Grep disabled), so never deny spawning it.
    "allow_agents": ["research-assistant"],
}


@hook_group.command("pretooluse")
def hook_pretooluse() -> None:
    """Gate Agent/Task spawns so subagents are forced to search via BrainPalace.

    ON by default, but ONLY when this project's BrainPalace server is actually
    running (``discover_server_url`` validates runtime.json + a live PID +
    ``GET /health/``). No live server → no denial: it is pointless to force
    BrainPalace-only search when BrainPalace cannot answer, so subagents may fall
    back to grep until the server is up. When a guarded spawn's prompt carries
    no ``brainpalace query --mode`` directive (or opens with a bypass
    instruction), the guard reacts per ``cli.subagent_guard.mode``:
      - ``enforce`` (default) → deny the spawn with a fix hint;
      - ``advisory`` → allow but inject a nudge (subagents often ignore nudges —
        that is why ``enforce`` is the default).
    Disable with ``cli.subagent_guard.enabled: false`` or
    ``BRAINPALACE_SUBAGENT_GUARD=off``.
    Fail-soft: any error → allow (emit nothing). Never blocks on a crash.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if payload.get("tool_name") not in ("Agent", "Task"):
            return
        # Only police when a live server can actually serve queries. No running
        # server → not our concern (don't block grep when BrainPalace is down).
        if discover_server_url(None) is None:
            return
        cfg = _load_guard_config()
        if not cfg["enabled"]:
            return
        tool_input = payload.get("tool_input") or {}
        subagent = tool_input.get("subagent_type") or "general-purpose"
        if subagent in cfg["allow_agents"]:
            return
        prompt = tool_input.get("prompt") or ""
        if _guard_prompt_ok(prompt):
            return
        if cfg["mode"] == "advisory":
            click.echo(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "additionalContext": _GUARD_DENY_REASON,
                        }
                    }
                )
            )
            return
        click.echo(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": _GUARD_DENY_REASON,
                    }
                }
            )
        )
    except Exception:  # noqa: BLE001 — a hook must NEVER crash/block a session
        pass


def _guard_prompt_ok(prompt: str) -> bool:
    """True when the prompt may spawn (valid exemption, or has a query directive)."""
    # Layer 1: explicit exemption marker in first 3 non-blank lines, reason >= 20 chars.
    non_blank = [ln for ln in prompt.splitlines() if ln.strip()][:3]
    for line in non_blank:
        m = _GUARD_EXEMPT_RE.match(line.strip())
        if m and len(m.group(1).strip()) >= 20:
            return True
    # Layer 2: prompt must carry a BrainPalace query directive.
    if not _GUARD_DIRECTIVE_RE.search(prompt):
        return False
    # Layer 3: reject prompts that open by telling the subagent to skip BrainPalace.
    if _GUARD_BYPASS_RE.search(prompt[:200]):
        return False
    return True


def _load_guard_config() -> dict[str, Any]:
    """Resolve ``cli.subagent_guard`` from global XDG + project config (project wins).

    Env override ``BRAINPALACE_SUBAGENT_GUARD`` (off|advisory|enforce) takes top
    precedence. Best-effort: returns defaults on any failure so the hook fails open.
    """
    cfg: dict[str, Any] = dict(_GUARD_DEFAULTS)
    cfg["allow_agents"] = list(_GUARD_DEFAULTS["allow_agents"])
    for raw in _guard_config_sources():
        guard = (raw.get("cli") or {}).get("subagent_guard")
        if not isinstance(guard, dict):
            continue
        if isinstance(guard.get("enabled"), bool):
            cfg["enabled"] = guard["enabled"]
        if guard.get("mode") in ("advisory", "enforce"):
            cfg["mode"] = guard["mode"]
        if isinstance(guard.get("allow_agents"), list):
            cfg["allow_agents"] = [str(a) for a in guard["allow_agents"]]
    env = os.getenv("BRAINPALACE_SUBAGENT_GUARD", "").strip().lower()
    if env in ("off", "false", "0", "disabled"):
        cfg["enabled"] = False
    elif env in ("advisory", "enforce"):
        cfg["enabled"] = True
        cfg["mode"] = env
    return cfg


def _guard_config_sources() -> list[dict[str, Any]]:
    """Raw config dicts, global first then project (so project overrides global)."""
    import yaml

    sources: list[dict[str, Any]] = []
    candidates: list[Path] = [get_xdg_config_dir() / "config.yaml"]
    project = discover_project_dir(None)
    if project is not None:
        candidates.append(project / ".brainpalace" / "config.yaml")
    for path in candidates:
        try:
            if path.is_file():
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    sources.append(data)
        except Exception:
            continue
    return sources


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

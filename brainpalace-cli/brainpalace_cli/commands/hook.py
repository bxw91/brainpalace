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
import shutil
import subprocess
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


@hook_group.command("userpromptsubmit")
def hook_userpromptsubmit() -> None:
    """Drain one throttled batch of the unified extraction queue after a user turn.

    Indexed projects only (silent no-op otherwise). Fetches ``source=all``
    pending items, throttles docs + sessions per source, and — on a non-empty,
    non-cooldown batch — injects ONE ids-only directive routing doc ids to a
    single ``graph-triplet-extractor`` dispatch and session ids to one
    ``chat-session-extractor`` each. Selection, byte budget, per-source caps and
    the cooldown-on-emit live in :func:`extraction_drain.unified_drain`
    (unit-tested). The directive carries **ids only, never chunk text** (H1).
    Empty drain / active cooldown / server down → emit nothing. Never blocks.
    """
    try:
        # Lazy import: keeps the hook module light + avoids an import cycle.
        from .extraction_drain import (
            resolve_budget,
            resolve_cooldown,
            resolve_doc_cap,
            resolve_max_pending,
            resolve_session_cap,
            unified_drain,
        )

        root = discover_project_dir(None)
        if root is None:
            return  # not an indexed project → never touch it.
        url = discover_server_url(None)
        if url is None:
            return  # server down → fail open, inject nothing.
        out = unified_drain(
            root,
            url=url,
            doc_cap=resolve_doc_cap(root),
            session_budget=resolve_budget(root),
            session_cap=resolve_session_cap(root),
            cooldown=resolve_cooldown(root),
            max_pending=resolve_max_pending(root),
        )
        directive = out.get("directive")
        if not directive:
            return  # empty queue / active cooldown / error → inject nothing.
        click.echo(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": directive,
                    }
                }
            )
        )
    except Exception:  # noqa: BLE001 — a hook must NEVER crash/block a session
        pass


# --- subagent guard (PreToolUse) ------------------------------------------

# Query modes a guarded subagent prompt must reference to prove it will search
# via BrainPalace. Mirrors the modes accepted by `brainpalace query --mode` and
# the MCP/skill `query` tool's `mode` argument.
_GUARD_QUERY_MODES = ("hybrid", "bm25", "vector", "graph", "multi")
_GUARD_MODES_ALT = "|".join(_GUARD_QUERY_MODES)
# A prompt proves BrainPalace search two equivalent ways:
#   CLI form — `brainpalace query ... --mode <mode>`
#   MCP form — the MCP/skill `query` tool (no `--mode` flag) carrying a mode
#              argument near a `brainpalace` mention: `mode: hybrid`,
#              `mode=graph`, `"mode": "vector"`.
# Either satisfies the guard; matching either errs toward allowing the spawn,
# which is the safe (fail-open) direction.
_GUARD_DIRECTIVE_CLI_RE = re.compile(
    rf"brainpalace\s+query\s+.*--mode\s+(?:{_GUARD_MODES_ALT})",
    re.IGNORECASE,
)
_GUARD_DIRECTIVE_MCP_RE = re.compile(
    rf"brainpalace[\s\S]{{0,200}}?\bmode\b[\"']?\s*[:=]\s*[\"']?(?:{_GUARD_MODES_ALT})\b",
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
    # Default mode is ``advisory`` (nudge, never deny). Rationale: this guard is
    # ON by default and fires on EVERY Agent/Task spawn once the server is up,
    # including agents from OTHER plugins it knows nothing about (Explore, Plan,
    # gsd-*, caveman, …). A default that silently DENIES those spawns is too
    # blunt — an on-by-default feature should not block by default. Advisory
    # keeps the BrainPalace-search nudge without the cross-plugin breakage.
    #
    # To restore hard blocking, set this back to ``"enforce"`` (and re-point
    # ``test_default_config_*``). Enforce has more teeth because subagents often
    # ignore an advisory nudge; prefer it only when every spawned agent in the
    # project is expected to search via BrainPalace. Per-project opt-in stays
    # available via ``cli.subagent_guard.mode: enforce`` or
    # ``BRAINPALACE_SUBAGENT_GUARD=enforce``.
    "mode": "advisory",
    # The shipped brainpalace research agent is BrainPalace-only by construction
    # (Glob/Grep disabled), so never deny spawning it.
    "allow_agents": ["research-assistant"],
}


# --- search guard (PreToolUse, main thread) -------------------------------

# The main thread's own search tools. Bash is intentionally absent: the
# PreToolUse matcher fires per tool *name*, so guarding Bash would spawn this
# hook on EVERY shell command (~0.3s cold start each) — far too costly for an
# on-by-default feature. Grep/Glob are dedicated, always-a-search tools that
# fire rarely, and dropping to `grep`/`find` via Bash is the deliberate escape
# hatch for raw search of non-indexed files.
_SEARCH_GUARD_TOOLS = ("Grep", "Glob")
_SEARCH_GUARD_DEFAULTS: dict[str, Any] = {
    # On by default, but advisory (nudge, never deny) — same rationale as the
    # subagent guard: an on-by-default guard that silently DENIED every Grep/Glob
    # would be far too blunt (it also fires on other plugins' searches). Advisory
    # keeps the BrainPalace nudge without breaking workflows. Opt into hard
    # blocking with ``cli.search_guard.mode: enforce`` or
    # ``BRAINPALACE_SEARCH_GUARD=enforce``.
    "enabled": True,
    "mode": "advisory",
}
_SEARCH_DENY_REASON = (
    "BrainPalace is indexed and running for this project — search it instead of "
    'Grep/Glob: `brainpalace query "..." --mode bm25` for exact '
    "symbols/tokens/paths (no embedding round-trip, ms latency) or `--mode "
    "hybrid` for concepts. For raw search of non-indexed files, run `grep`/`find` "
    "via Bash (not guarded). Disable with `cli.search_guard.enabled: false` or "
    "`BRAINPALACE_SEARCH_GUARD=off`."
)


@hook_group.command("pretooluse")
def hook_pretooluse() -> None:
    """Steer the session toward BrainPalace search instead of grep/glob/find.

    Two sibling guards share this one PreToolUse entry point, dispatched by
    ``tool_name``:
      - **subagent guard** (``Agent``/``Task``) — gate spawns so subagents are
        forced to search via BrainPalace (``cli.subagent_guard.*``);
      - **search guard** (``Grep``/``Glob``) — steer the main thread's own search
        the same way (``cli.search_guard.*``).
    Both are ON by default, but ONLY when this project's BrainPalace server is
    actually running (``discover_server_url`` validates runtime.json + a live PID
    + ``GET /health/``). No live server → no action: pointless to force
    BrainPalace-only search when BrainPalace cannot answer. Each guard's
    ``mode`` decides the reaction — ``advisory`` (default) injects a nudge,
    ``enforce`` denies with a fix hint. Disable per guard via its
    ``enabled: false`` or env kill-switch.
    Fail-soft: any error → allow (emit nothing). Never blocks on a crash.
    """
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        tool = payload.get("tool_name")
        if tool in ("Agent", "Task"):
            _subagent_guard(payload)
        elif tool in _SEARCH_GUARD_TOOLS:
            _search_guard()
    except Exception:  # noqa: BLE001 — a hook must NEVER crash/block a session
        pass


def _emit_pretooluse(mode: str, reason: str) -> None:
    """Emit the PreToolUse decision: advisory → nudge, else → deny."""
    hso: dict[str, Any] = {"hookEventName": "PreToolUse"}
    if mode == "advisory":
        hso["additionalContext"] = reason
    else:
        hso["permissionDecision"] = "deny"
        hso["permissionDecisionReason"] = reason
    click.echo(json.dumps({"hookSpecificOutput": hso}))


def _subagent_guard(payload: dict[str, Any]) -> None:
    """Gate an Agent/Task spawn: prompt must carry a BrainPalace query directive."""
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
    _emit_pretooluse(cfg["mode"], _GUARD_DENY_REASON)


def _search_guard() -> None:
    """Steer a main-thread Grep/Glob toward BrainPalace search (when server up)."""
    if discover_server_url(None) is None:
        return
    cfg = _load_search_guard_config()
    if not cfg["enabled"]:
        return
    _emit_pretooluse(cfg["mode"], _SEARCH_DENY_REASON)


def _guard_prompt_ok(prompt: str) -> bool:
    """True when the prompt may spawn (valid exemption, or has a query directive)."""
    # Layer 1: explicit exemption marker in first 3 non-blank lines, reason >= 20 chars.
    non_blank = [ln for ln in prompt.splitlines() if ln.strip()][:3]
    for line in non_blank:
        m = _GUARD_EXEMPT_RE.match(line.strip())
        if m and len(m.group(1).strip()) >= 20:
            return True
    # Layer 2: prompt must carry a BrainPalace query directive (CLI or MCP form).
    if not (
        _GUARD_DIRECTIVE_CLI_RE.search(prompt) or _GUARD_DIRECTIVE_MCP_RE.search(prompt)
    ):
        return False
    # Layer 3: reject prompts that open by telling the subagent to skip BrainPalace.
    if _GUARD_BYPASS_RE.search(prompt[:200]):
        return False
    return True


def _resolve_enabled_mode(
    config_key: str, env_var: str, defaults: dict[str, Any]
) -> dict[str, Any]:
    """Resolve a guard's ``enabled``/``mode`` from global XDG + project config.

    Project overrides global; env override (off|advisory|enforce) takes top
    precedence. Shared by both PreToolUse guards. Best-effort: returns defaults on
    any failure so the hook fails open.
    """
    cfg: dict[str, Any] = {"enabled": defaults["enabled"], "mode": defaults["mode"]}
    for raw in _guard_config_sources():
        guard = (raw.get("cli") or {}).get(config_key)
        if not isinstance(guard, dict):
            continue
        if isinstance(guard.get("enabled"), bool):
            cfg["enabled"] = guard["enabled"]
        if guard.get("mode") in ("advisory", "enforce"):
            cfg["mode"] = guard["mode"]
    env = os.getenv(env_var, "").strip().lower()
    if env in ("off", "false", "0", "disabled"):
        cfg["enabled"] = False
    elif env in ("advisory", "enforce"):
        cfg["enabled"] = True
        cfg["mode"] = env
    return cfg


def _load_guard_config() -> dict[str, Any]:
    """Resolve ``cli.subagent_guard`` from global XDG + project config (project wins).

    Env override ``BRAINPALACE_SUBAGENT_GUARD`` (off|advisory|enforce) takes top
    precedence. Best-effort: returns defaults on any failure so the hook fails open.
    """
    cfg = _resolve_enabled_mode(
        "subagent_guard", "BRAINPALACE_SUBAGENT_GUARD", _GUARD_DEFAULTS
    )
    cfg["allow_agents"] = list(_GUARD_DEFAULTS["allow_agents"])
    for raw in _guard_config_sources():
        guard = (raw.get("cli") or {}).get("subagent_guard")
        if isinstance(guard, dict) and isinstance(guard.get("allow_agents"), list):
            cfg["allow_agents"] = [str(a) for a in guard["allow_agents"]]
    return cfg


def _load_search_guard_config() -> dict[str, Any]:
    """Resolve ``cli.search_guard`` from global XDG + project config (project wins).

    Env override ``BRAINPALACE_SEARCH_GUARD`` (off|advisory|enforce) takes top
    precedence. Best-effort: returns defaults on any failure so the hook fails open.
    """
    return _resolve_enabled_mode(
        "search_guard", "BRAINPALACE_SEARCH_GUARD", _SEARCH_GUARD_DEFAULTS
    )


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


def _session_autostart_enabled() -> bool:
    """Resolve ``cli.session_autostart`` (global XDG + project, project wins).

    Env override ``BRAINPALACE_SESSION_AUTOSTART`` (off|on) takes top precedence.
    Default ``True``. Best-effort: any failure returns the default so the hook
    fails toward the documented on-by-default behavior.
    """
    env = os.getenv("BRAINPALACE_SESSION_AUTOSTART", "").strip().lower()
    if env in ("off", "false", "0", "disabled"):
        return False
    if env in ("on", "true", "1", "enabled"):
        return True
    enabled = True
    for raw in _guard_config_sources():
        cli = raw.get("cli")
        if isinstance(cli, dict) and isinstance(cli.get("session_autostart"), bool):
            enabled = cli["session_autostart"]
    return enabled


def _spawn_autostart(project: Path) -> None:
    """Launch ``brainpalace start --json`` fully detached, never waiting on it.

    ``brainpalace start`` daemonizes the server but blocks on a health-wait; the
    SessionStart hook must NEVER block, so we fire-and-forget in a new session
    with all stdio discarded. `--json` keeps the dashboard headless (no browser).
    Fail-soft: any error is swallowed — a failed autostart must not break the
    session, the NUDGE still tells the AI the project is indexed.
    """
    try:
        prog = shutil.which("brainpalace") or sys.argv[0]
        subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            [prog, "start", "--json"],
            cwd=str(project),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001 — autostart is best-effort; never blocks
        pass


def _dashboard_autostart_enabled() -> bool:
    """Whether the singleton web dashboard should be auto-launched.

    Mirrors the gate ``brainpalace start`` uses (``dashboard.autostart``).
    Best-effort: if the dashboard package is absent (Python < 3.12) or the config
    can't be read, returns False so the hook never tries to start something
    unavailable or that the user turned off.
    """
    try:
        from brainpalace_dashboard.config import (  # noqa: PLC0415
            load_dashboard_config,
        )

        return bool(load_dashboard_config().autostart)
    except Exception:  # noqa: BLE001
        return False


def _spawn_dashboard_autostart(project: Path) -> None:
    """Detached, best-effort ``brainpalace dashboard start --no-open``.

    Resurrects the singleton dashboard when the SERVER is already up but the
    dashboard has died. The dashboard is launched on ``brainpalace start`` and is
    NOT supervised, so a graceful stop (e.g. a reinstall) would otherwise leave it
    down until the next ``start`` — and the server-down autostart path never fires
    while the server is up. Idempotent: ``dashboard start`` refuses (no-ops) when a
    healthy dashboard is already tracked, so firing this every session start is
    safe and non-blocking.
    """
    try:
        prog = shutil.which("brainpalace") or sys.argv[0]
        subprocess.Popen(  # noqa: S603 — fixed argv, no shell
            [prog, "dashboard", "start", "--no-open"],
            cwd=str(project),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: BLE001 — best-effort; never blocks the hook
        pass


def _emit_sessionstart() -> None:
    project = discover_project_dir(None)
    if project is None:
        return  # whoami exit-1 equivalent: silent no-op for non-indexed projects.

    msg = nudge()
    if not msg:
        return  # bundled guidance unavailable → fail soft, emit nothing.

    url = discover_server_url(None)
    if url is None and _session_autostart_enabled():
        # Indexed project, server down → bring it up (server + headless dashboard)
        # in the background so this session can search without a manual `start`.
        _spawn_autostart(project)
    if url:
        # Server up but the dashboard may have died (it is launched on
        # `brainpalace start`, not supervised; the server-down autostart above
        # never fires while the server is up). Best-effort, detached: resurrect it
        # so it does not stay down after a graceful stop / reinstall.
        if _session_autostart_enabled() and _dashboard_autostart_enabled():
            _spawn_dashboard_autostart(project)
        # Append the frozen-snapshot context block (project facts + curated
        # memory). Fail soft — a context error must not drop the NUDGE.
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

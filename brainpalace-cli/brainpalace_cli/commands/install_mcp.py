"""``install-mcp`` — write BrainPalace's MCP server into the project's
``.mcp.json``.

Mirrors ``install-session-hooks``: a small, idempotent, dedicated installer.
Unlike the SessionStart hook (which lives under ``~/.claude/``), an MCP
server declaration is **per-project** (D7) — it belongs in the project's own
``.mcp.json`` so it loads only where BrainPalace is actually configured.

``init`` calls this automatically (unless ``--no-mcp``), but ``init`` is not
re-runnable on an already-initialized project without ``--force``
(``init.py`` ``config_path.exists() and not force``). This command is
therefore the *only* route for every already-initialized project to adopt
MCP — see D12 in the search-routing-and-mcp-surface spec.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Any, NamedTuple

import click

#: The exact server declaration this command merges into .mcp.json. Source
#: of truth is brainpalace-plugin/templates/mcp-config-claude-code.json,
#: with its `_comment_*` keys dropped. No --ensure-server: the SessionStart
#: hook already autostarts the server (see the template's _comment_4).
_SERVER_KEY = "brainpalace"
_SERVER_CONFIG: dict[str, Any] = {
    "command": "brainpalace",
    "args": ["mcp"],
}

#: Writing .mcp.json only *declares* the server: Claude Code holds a
#: .mcp.json server at "⏸ Pending approval" until it is approved out-of-band,
#: because .mcp.json is committed and a clone must not silently execute what
#: it declares. Approval therefore lives in settings, and per Claude Code's
#: docs `enabledMcpjsonServers` is honoured in an untrusted folder only from
#: a settings file that is NOT checked into the repo. `.claude/settings.local.json`
#: is exactly that (gitignored, per-project, per-user), so recording approval
#: there is a deliberate local act by the user who ran this command — not repo
#: content approving itself. A clone still gets "Pending approval". Scope is
#: per-project on purpose: ~/.claude/settings.json would approve a
#: `brainpalace`-named server in EVERY project.
_APPROVAL_SETTINGS_REL = Path(".claude") / "settings.local.json"
_ENABLED_KEY = "enabledMcpjsonServers"
_DISABLED_KEY = "disabledMcpjsonServers"

#: D15/D17 — the tools do not appear in the CURRENT session; MCP servers are
#: loaded at session start, so they arrive at the next one. Recording approval
#: removes the per-server "approve this MCP server?" step, so the notice no
#: longer sends the user to a prompt that will not appear.
#:
#: It still mentions folder trust, because that gate is NOT ours to close and
#: measurably outranks the allowlist: in an untrusted folder Claude Code holds
#: the server at "Pending approval" even with enabledMcpjsonServers set
#: (verified empirically — same allowlist connects under a trusted parent and
#: stays pending under /tmp, with and without the settings file gitignored).
#: Trust is granted once per folder and cannot be conferred by any file we
#: write; claiming "approved, just restart" would strand exactly the user this
#: change exists to unstrand.
#:
#: `changed=True` only — the file genuinely did not have the entry a moment
#: ago, so "not available in this session" is a fact, not a guess.
_RESTART_NOTICE = (
    "BrainPalace MCP tools were written to .mcp.json and approved for this "
    "project. They do not appear in this session — MCP servers load only at "
    "session start, so restart Claude Code to pick them up. If you have not "
    "trusted this folder before, accept the trust prompt when it appears; "
    "an untrusted folder holds its MCP servers at 'Pending approval'."
)

#: `--no-approve`, or an explicit disabledMcpjsonServers entry: the entry is
#: declared but NOT approved, so the user must still approve it themselves.
_UNAPPROVED_NOTICE = (
    "BrainPalace MCP tools were written to .mcp.json but are NOT approved for "
    "this project, so Claude Code will hold them at 'Pending approval'. "
    "Restart Claude Code and approve the project's MCP servers when prompted, "
    "or run `brainpalace install-mcp` without --no-approve."
)

#: Non-TTY path (D17): the agent-run case. Directs Claude to use
#: AskUserQuestion rather than asking it to relay prose — mirrors the shape
#: of hook.py's _SETUP_NUDGE_DIRECTIVE, the codebase's own stronger idiom for
#: "this needs to reach the user, not just the tool result". `changed=True`
#: only — same reasoning as _RESTART_NOTICE above.
_MCP_RESTART_DIRECTIVE = (
    "NOTE: BrainPalace MCP tools were written to .mcp.json and approved for "
    "this project, but are NOT available in this session — MCP servers load "
    "only at session start. Use the AskUserQuestion tool to ask the user: "
    "(A) restart Claude Code now to load the BrainPalace MCP tools, or "
    "(B) later. Do NOT claim the tools are already available. If the user "
    "has not trusted this folder before, tell them to accept the trust "
    "prompt on restart — an untrusted folder holds its MCP servers at "
    "'Pending approval' regardless of the approval just recorded."
)

#: Local scope: no approval prompt AND no folder-trust prompt — the server
#: lives in the user's own ~/.claude.json, not in the repo. Mentioning trust
#: here would be the same overclaiming in reverse: sending the user to look
#: for a dialog that will not appear.
_LOCAL_RESTART_NOTICE = (
    "BrainPalace MCP tools are registered for this project. They do not appear "
    "in this session — MCP servers load only at session start, so restart "
    "Claude Code to pick them up. No approval is needed."
)

_LOCAL_RESTART_DIRECTIVE = (
    "NOTE: BrainPalace MCP tools are registered for this project but are NOT "
    "available in this session — MCP servers load only at session start. No "
    "approval is needed; a restart is enough. Use the AskUserQuestion tool to "
    "ask the user: (A) restart Claude Code now to load the BrainPalace MCP "
    "tools, or (B) later. Do NOT claim the tools are already available."
)

#: Non-TTY twin of _UNAPPROVED_NOTICE — same D17 reasoning.
_UNAPPROVED_DIRECTIVE = (
    "NOTE: BrainPalace MCP tools were written to .mcp.json but were NOT "
    "approved, so Claude Code will hold them at 'Pending approval' and they "
    "are NOT available in this session. Use the AskUserQuestion tool to ask "
    "the user: (A) restart Claude Code now and approve the project's MCP "
    "servers when prompted, or (B) later. Do NOT claim the tools are already "
    "available."
)

#: `changed=False` — the entry was ALREADY in .mcp.json before this run. The
#: CLI cannot see whether the calling session already loaded it (dogfooding
#: found this run live, with the tools genuinely connected) — asserting they
#: are unavailable would be false, and worse than silence: it would make the
#: agent contradict a session that is actually working. So this path stays
#: conditional and does not tell the agent to ask anything — nothing changed.
_ALREADY_INSTALLED_NOTICE = (
    "BrainPalace's MCP entry is already in .mcp.json and approved for this "
    "project. If the brainpalace MCP tools are not available in your current "
    "session, restart Claude Code to pick them up."
)


#: Claude Code's own local scope: the server lives in ~/.claude.json under the
#: project's entry, NOT in the repo. That distinction is the whole reason this
#: path needs no approval — .mcp.json is committed and reaches anyone who
#: clones the repo, so Claude Code treats it as untrusted input and holds it at
#: "Pending approval"; ~/.claude.json is the user's own machine config, so a
#: server registered there by the user's own command is trusted by
#: construction. Verified: a local-scope server connects in an UNTRUSTED /tmp
#: folder with hasTrustDialogAccepted=False and no .mcp.json present at all.
#:
#: We shell out to `claude mcp add` rather than editing ~/.claude.json
#: ourselves: Claude Code rewrites that file wholesale on exit, so a direct
#: write races any running session and loses. Reading it is safe, so detection
#: reads and only the write shells out.
_CLAUDE_ADD_TIMEOUT_S = 30


def local_scope_has_server(project_root: Path) -> bool:
    """Is ``brainpalace`` already registered in Claude Code's local scope here?

    Reads ~/.claude.json directly (safe — only writes race a running session).
    `claude mcp get` cannot answer this: it exits 0 for a server in ANY scope,
    including a .mcp.json entry sitting at "Pending approval", which is exactly
    the state we are trying to fix.
    """
    try:
        data = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    project = data.get("projects", {}).get(str(project_root))
    if not isinstance(project, dict):
        return False
    servers = project.get("mcpServers")
    return isinstance(servers, dict) and _SERVER_KEY in servers


def register_local_scope(project_root: Path) -> tuple[bool, str | None]:
    """Register the server in Claude Code's local scope via ``claude mcp add``.

    Returns ``(changed, error)``. ``error`` is a human-readable reason the
    caller can fall back on — a missing `claude` binary is the expected case
    (BrainPalace does not depend on Claude Code), not a failure.

    Not idempotent upstream: a second `claude mcp add` exits 1 with "already
    exists in local config", so we detect first and skip.
    """
    if local_scope_has_server(project_root):
        return False, None

    claude_bin = which("claude")
    if claude_bin is None:
        return False, "the `claude` CLI is not on PATH"

    try:
        proc = subprocess.run(
            [
                claude_bin,
                "mcp",
                "add",
                _SERVER_KEY,
                "-s",
                "local",
                "--",
                *[_SERVER_CONFIG["command"], *_SERVER_CONFIG["args"]],
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=_CLAUDE_ADD_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"`claude mcp add` failed to run: {e}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, f"`claude mcp add` failed: {detail[-1] if detail else 'unknown'}"
    return True, None


def approve_mcp_server(project_root: Path) -> tuple[bool, str | None]:
    """Record approval for the ``brainpalace`` .mcp.json server.

    Appends ``brainpalace`` to ``enabledMcpjsonServers`` in the project's
    ``.claude/settings.local.json``. Merges into any existing settings
    (permissions, hooks, …) rather than replacing them — same never-clobber
    discipline `install_mcp` applies to ``.mcp.json`` (A10).

    Deliberately narrow: it appends ONE server name to the allowlist and never
    sets ``enableAllProjectMcpServers``, which would approve every server the
    project declares (``context7``, ``supabase``, anything a clone adds later).

    Returns ``(approved, skip_reason)`` where ``approved`` is the END STATE —
    True if the server is approved when this returns, including when it
    already was and nothing needed writing.

    An explicit ``disabledMcpjsonServers`` entry wins — the denylist takes
    precedence in Claude Code, so writing the allowlist over it would be
    silently inert, and overriding a choice the user made by hand is not this
    command's call.

    Raises ``ValueError`` if the settings file exists but cannot be parsed —
    it holds the user's permissions and hooks; a malformed file must fail
    loudly, never be overwritten.
    """
    settings_path = project_root / _APPROVAL_SETTINGS_REL
    settings: dict[str, Any] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"Could not parse existing {settings_path}: {e}") from e
        if not isinstance(settings, dict):
            raise ValueError(
                f"Existing {settings_path} does not contain a JSON object at "
                "the top level — refusing to overwrite."
            )

    disabled = settings.get(_DISABLED_KEY)
    if isinstance(disabled, list) and _SERVER_KEY in disabled:
        return False, (
            f"{_SERVER_KEY} is listed in {_DISABLED_KEY} in {settings_path} — "
            "leaving that explicit choice alone."
        )

    enabled = settings.get(_ENABLED_KEY)
    if not isinstance(enabled, list):
        enabled = []
    if _SERVER_KEY in enabled:
        return True, None  # already approved — end state is what matters

    settings[_ENABLED_KEY] = [*enabled, _SERVER_KEY]
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return True, None


def merge_mcp_config(existing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Merge the ``brainpalace`` server into an existing ``.mcp.json`` dict.

    Never clobbers other servers (A10) — a project may already declare
    ``context7``, ``supabase``, etc. Returns ``(merged, changed)``; ``changed``
    is False when the key was already present and identical (idempotent
    re-run — no duplicate, no unnecessary write).
    """
    merged = copy.deepcopy(existing)
    servers = merged.setdefault("mcpServers", {})
    if servers.get(_SERVER_KEY) == _SERVER_CONFIG:
        return merged, False
    servers[_SERVER_KEY] = copy.deepcopy(_SERVER_CONFIG)
    return merged, True


class InstallResult(NamedTuple):
    """Outcome of one ``install_mcp`` call.

    ``changed`` is True only when THIS call wrote ``.mcp.json``, so a re-run
    reports False and the notice stays honest about what it actually did.

    ``approved`` is the END STATE, not "this call wrote it": True whenever the
    server is approved once this call returns, whether it was already approved
    or we just recorded it. The notice needs to know whether Claude Code will
    connect — not who wrote the file — and conflating the two made a re-run
    claim the server was unapproved when it was fine.

    ``approved`` is True whenever Claude Code will connect to the server once
    this call returns — whether that is because it is registered in local
    scope (which needs no approval at all) or because the .mcp.json entry is
    allowlisted.

    ``scope`` records which route got there: "local" (registered in
    ~/.claude.json — no approval, no folder trust needed) or "project"
    (.mcp.json + allowlist, which folder trust still gates).

    ``skip_reason`` explains a deliberate non-approval (the user disabled the
    server by hand); None otherwise. ``fallback_reason`` explains why local
    scope was not used when it was wanted — normally a missing `claude` CLI.
    """

    config: dict[str, Any]
    changed: bool
    approved: bool
    skip_reason: str | None
    scope: str = "project"
    fallback_reason: str | None = None


def install_mcp(
    project_root: Path, *, approve: bool = True, scope: str = "auto"
) -> InstallResult:
    """Write/merge the BrainPalace MCP server into ``<project_root>/.mcp.json``
    and make Claude Code actually connect to it.

    ``.mcp.json`` is always written (it is the shareable declaration, and it is
    what non-Claude-Code readers of the repo see). It is not enough on its own:
    Claude Code holds a .mcp.json server at "Pending approval" until it is
    approved, so declaring one and stopping is a half-installed feature.

    ``scope`` picks how the connection is actually granted:

    - ``"auto"`` (default): register in Claude Code's **local scope**, which
      needs no approval and no folder trust. Falls back to ``"project"`` when
      the `claude` CLI is absent — BrainPalace does not depend on Claude Code.
    - ``"local"``: local scope only; reports the reason if it cannot.
    - ``"project"``: allowlist the .mcp.json entry instead, no `claude` needed.
      Folder trust still gates this route.

    Local scope wins over .mcp.json in Claude Code, so writing both is not a
    conflict and produces no duplicate — verified.

    With ``approve=False``, the entry is declared and nothing grants it.

    Raises ``ValueError`` if an existing ``.mcp.json`` cannot be parsed — a
    malformed file must fail loudly, not be silently overwritten (A10).
    """
    if scope not in ("auto", "local", "project"):
        raise ValueError(f"unknown scope {scope!r} — use auto, local or project")
    mcp_path = project_root / ".mcp.json"
    existing: dict[str, Any] = {}
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"Could not parse existing {mcp_path}: {e}") from e
        if not isinstance(existing, dict):
            raise ValueError(
                f"Existing {mcp_path} does not contain a JSON object at the "
                "top level — refusing to overwrite."
            )

    merged, changed = merge_mcp_config(existing)
    if changed:
        mcp_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    if not approve:
        return InstallResult(merged, changed, False, None, scope="project")

    # Local scope first: it is the only route that needs neither per-server
    # approval nor folder trust.
    fallback_reason: str | None = None
    if scope in ("auto", "local"):
        registered, err = register_local_scope(project_root)
        if err is None:
            # registered now, or already there from a previous run — either way
            # Claude Code will connect, which is what `approved` reports.
            return InstallResult(merged, changed, True, None, scope="local")
        fallback_reason = err
        if scope == "local":
            return InstallResult(merged, changed, False, None, "local", fallback_reason)

    approved, skip_reason = approve_mcp_server(project_root)
    return InstallResult(
        merged, changed, approved, skip_reason, "project", fallback_reason
    )


def restart_notice(
    *,
    changed: bool = True,
    is_tty: bool | None = None,
    approved: bool = True,
    scope: str = "project",
) -> str:
    """The D15/D17 restart notice, split by TTY — and by whether this call
    actually changed anything.

    ``changed=True`` (the file genuinely did not have the entry a moment
    ago): a human at a terminal gets a plain confident line; a non-TTY
    caller (an agent running the command via Bash — the common plugin-user
    path) gets an AskUserQuestion directive instead of prose hoping to be
    relayed (D17): "please relay this" is instruction-level guidance, and
    this whole spec exists because such guidance gets skipped.

    ``changed=False`` (the entry was already there — e.g. a re-run after
    the user already restarted): the CLI cannot see whether the calling
    session loaded the tools, so both paths soften to conditional wording and
    neither instructs an AskUserQuestion prompt — nothing changed, so there is
    nothing new to ask about.

    ``approved=False`` (--no-approve, or the user disabled the server by
    hand): the entry is declared but Claude Code will hold it at "Pending
    approval", so the notice must still tell the user to approve it. Claiming
    a restart is enough would strand them at exactly the ⏸ state this
    command's approval step exists to prevent.
    """
    if is_tty is None:
        is_tty = sys.stdout.isatty()
    if not changed:
        return _ALREADY_INSTALLED_NOTICE
    if not approved:
        return _UNAPPROVED_NOTICE if is_tty else _UNAPPROVED_DIRECTIVE
    if scope == "local":
        # No approval, no trust gate — say only what is true of this route.
        return _LOCAL_RESTART_NOTICE if is_tty else _LOCAL_RESTART_DIRECTIVE
    return _RESTART_NOTICE if is_tty else _MCP_RESTART_DIRECTIVE


@click.command("install-mcp")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--no-approve",
    is_flag=True,
    help=(
        "Declare the server in .mcp.json but do not approve it. Claude Code "
        "will hold it at 'Pending approval' until you approve it yourself."
    ),
)
@click.option(
    "--scope",
    type=click.Choice(["auto", "local", "project"]),
    default="auto",
    show_default=True,
    help=(
        "How to grant the connection. 'local' registers with Claude Code's "
        "local scope (no approval, no folder trust). 'project' allowlists the "
        ".mcp.json entry instead (no `claude` CLI needed, but folder trust "
        "still applies). 'auto' uses local and falls back to project."
    ),
)
def install_mcp_command(json_output: bool, no_approve: bool, scope: str) -> None:
    """Write BrainPalace's MCP server into the project's ``.mcp.json``.

    Merges a single ``mcpServers.brainpalace`` entry into any existing
    ``.mcp.json`` at the project root, preserving every other server already
    declared there. Idempotent: re-running does not duplicate or corrupt the
    file.

    Declaring the server is not enough on its own: Claude Code holds a
    ``.mcp.json`` server at "Pending approval" until it is granted. By default
    this command registers it with Claude Code's **local scope** (stored in
    your own ``~/.claude.json``, never in the repo), which needs no approval
    and no folder trust. If the ``claude`` CLI is not installed, it falls back
    to allowlisting the ``.mcp.json`` entry in the gitignored
    ``.claude/settings.local.json`` — approving ``brainpalace`` only, never
    every server the project declares. Either way the grant stays on this
    machine: a clone still starts unapproved. ``--no-approve`` opts out.

    The tools do not appear until the *next* Claude Code session — MCP servers
    load at session start. On a re-run that finds the entry already present,
    this command cannot tell whether your current session already has the
    tools loaded, so it says so conditionally instead of asserting either way.
    """
    project_root = Path.cwd()
    try:
        result = install_mcp(project_root, approve=not no_approve, scope=scope)
    except ValueError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e)}))
        else:
            click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    is_tty = sys.stdout.isatty()
    notice = restart_notice(
        changed=result.changed,
        is_tty=is_tty,
        approved=result.approved,
        scope=result.scope,
    )

    if json_output:
        payload: dict[str, Any] = {
            "status": "installed" if result.changed else "already_installed",
            "mcp_json": str(project_root / ".mcp.json"),
            "servers": sorted(result.config.get("mcpServers", {})),
            "approved": result.approved,
            "scope": result.scope,
            "notice": notice,
        }
        if result.skip_reason:
            payload["approval_skipped"] = result.skip_reason
        if result.fallback_reason:
            payload["local_scope_unavailable"] = result.fallback_reason
        click.echo(json.dumps(payload, indent=2))
    else:
        verb = "Installed" if result.changed else "Already installed"
        click.echo(f"{verb} BrainPalace MCP server into {project_root / '.mcp.json'}")
        if result.fallback_reason:
            click.echo(f"Local scope unavailable ({result.fallback_reason}).")
        if result.skip_reason:
            click.echo(f"Approval skipped: {result.skip_reason}")
        click.echo(notice)

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
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any, Literal, NamedTuple, NoReturn

import click
from rich.console import Console
from rich.panel import Panel

console = Console()

#: Human-facing client names for the result panel (fall back to the raw key).
#: Mirrors ``DISPLAY_NAMES`` in install_agent.py so both commands title their
#: green result boxes with the same tool name.
CLIENT_DISPLAY: dict[str, str] = {
    "claude": "Claude Code",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "vscode": "GitHub Copilot/VS Code",
    "kilo": "Kilo Code",
    "cline": "Cline",
    "qwen": "Qwen Code",
    "kimi": "Kimi CLI",
}

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


def merge_server(
    existing: dict[str, Any], top_key: str, server_key: str, entry: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Merge one server ``entry`` under ``existing[top_key][server_key]``.

    Generalises the Claude-only ``.mcp.json``/``mcpServers`` merge (A10) to any
    client's top-level key (``servers`` for VS Code, ``mcp`` for Kilo, …) and
    server dict key. Never clobbers other servers already declared under
    ``top_key``. Returns ``(merged, changed)``; ``changed`` is False when the
    key was already present and identical (idempotent re-run — no duplicate,
    no unnecessary write).
    """
    merged = copy.deepcopy(existing)
    servers = merged.setdefault(top_key, {})
    if not isinstance(servers, dict):
        raise ValueError(
            f"Existing {top_key!r} is not a JSON object — refusing to overwrite."
        )
    if servers.get(server_key) == entry:
        return merged, False
    servers[server_key] = copy.deepcopy(entry)
    return merged, True


def merge_mcp_config(existing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Merge the ``brainpalace`` server into an existing ``.mcp.json`` dict.

    Never clobbers other servers (A10) — a project may already declare
    ``context7``, ``supabase``, etc. Returns ``(merged, changed)``; ``changed``
    is False when the key was already present and identical (idempotent
    re-run — no duplicate, no unnecessary write).

    Thin wrapper over ``merge_server`` — kept so existing call sites and
    Claude's exact behaviour are unchanged (A2).
    """
    return merge_server(existing, "mcpServers", _SERVER_KEY, _SERVER_CONFIG)


# ---------------------------------------------------------------------------
# Per-client registry (B1) — the non-Claude MCP editors. Claude is NOT in this
# registry: its path predates --ensure-server and keeps its own approval /
# local-scope plumbing (D7), dispatched separately in install_mcp_command.
# Shapes/paths/keys are grounded in docs/MCP_SETUP.md (see the Phase B spec's
# "Grounded facts" table) — do not change without re-grounding there.
# ---------------------------------------------------------------------------

#: Every non-Claude client is told to autostart the server itself, since none
#: of them has BrainPalace's SessionStart hook to do it for them (D2).
_ENSURE_SERVER_ARGS = ["mcp", "--ensure-server"]

#: VS Code extension id owning Cline's MCP settings (D5).
_CLINE_EXTENSION_ID = "saoudrizwan.claude-dev"


def _base_entry() -> dict[str, Any]:
    """The shared base entry every non-Claude client wraps or reshapes (D2)."""
    return {"command": "brainpalace", "args": list(_ENSURE_SERVER_ARGS)}


def _vscode_entry() -> dict[str, Any]:
    return {"type": "stdio", **_base_entry()}


def _kilo_entry() -> dict[str, Any]:
    return {
        "type": "local",
        "command": ["brainpalace", *_ENSURE_SERVER_ARGS],
        "enabled": True,
        "timeout": 30000,
    }


def _cline_entry() -> dict[str, Any]:
    return {**_base_entry(), "disabled": False}


def _project_relative(rel_path: str) -> Callable[[Path], Path]:
    """A resolver rooted at ``project_root`` — for per-project config files."""
    return lambda project_root: project_root / rel_path


def _home_relative(rel_path: str) -> Callable[[Path], Path]:
    """A resolver rooted at the user's home dir — ``project_root`` is ignored.

    ``rel_path`` must start with ``~/``. Built from ``Path.home()`` rather
    than ``Path(rel_path).expanduser()`` — ``expanduser()`` reads
    ``$HOME``/the password database directly and does NOT go through
    ``Path.home()``, so it would silently ignore the
    ``patch("...install_mcp.Path.home", ...)`` isolation this codebase's own
    tests already rely on (see ``local_scope_has_server``'s tests) and hit
    the real home directory instead.
    """
    if not rel_path.startswith("~/"):
        raise ValueError(f"expected a '~/'-relative path, got {rel_path!r}")
    tail = rel_path[len("~/") :]

    def _resolve(_project_root: Path) -> Path:
        return Path.home() / tail

    return _resolve


def cline_settings_path(_project_root: Path) -> Path:
    """Resolve Cline's ``cline_mcp_settings.json`` inside VS Code's per-OS
    extension globalStorage (D5). Same file regardless of scope — Cline has
    no separate per-project location, so ``project_path`` and ``global_path``
    both point here.
    """
    if sys.platform == "darwin":
        code_user = Path.home() / "Library" / "Application Support" / "Code" / "User"
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        code_user = base / "Code" / "User"
    else:
        code_user = Path.home() / ".config" / "Code" / "User"
    ext_dir = code_user / "globalStorage" / _CLINE_EXTENSION_ID
    return ext_dir / "settings" / "cline_mcp_settings.json"


@dataclass(frozen=True)
class ClientDescriptor:
    """One non-Claude MCP client's config shape, location, and merge rules.

    ``project_path``/``global_path`` are callables taking ``project_root:
    Path -> Path``; a client with only one location (e.g. Cline, whose config
    lives in a per-user VS Code extension dir, not per-project) points both
    at the same resolver — ``--scope`` then selects the same file either way.
    """

    project_path: Callable[[Path], Path]
    global_path: Callable[[Path], Path]
    top_key: str
    entry_builder: Callable[[], dict[str, Any]]
    fmt: Literal["json", "jsonc"]
    default_scope: Literal["project", "global"]
    merge_strategy: Literal["standard", "cline-global-storage"] = "standard"


#: Registry of every non-Claude MCP client `install-mcp --client` can write.
#: Mirrors ``INSTALL_DIRS`` in install_agent.py: one code path, per-client data.
MCP_CLIENTS: dict[str, ClientDescriptor] = {
    "cursor": ClientDescriptor(
        project_path=_project_relative(".cursor/mcp.json"),
        global_path=_home_relative("~/.cursor/mcp.json"),
        top_key="mcpServers",
        entry_builder=_base_entry,
        fmt="json",
        default_scope="global",
    ),
    "windsurf": ClientDescriptor(
        # Global only (docs/MCP_SETUP.md) — no project-scoped config exists.
        project_path=_home_relative("~/.codeium/windsurf/mcp_config.json"),
        global_path=_home_relative("~/.codeium/windsurf/mcp_config.json"),
        top_key="mcpServers",
        entry_builder=_base_entry,
        fmt="json",
        default_scope="global",
    ),
    "vscode": ClientDescriptor(
        # Project only (docs/MCP_SETUP.md) — no global variant documented.
        project_path=_project_relative(".vscode/mcp.json"),
        global_path=_project_relative(".vscode/mcp.json"),
        top_key="servers",
        entry_builder=_vscode_entry,
        fmt="jsonc",
        default_scope="project",
    ),
    "kilo": ClientDescriptor(
        project_path=_project_relative(".kilo/kilo.jsonc"),
        global_path=_home_relative("~/.config/kilo/kilo.jsonc"),
        top_key="mcp",
        entry_builder=_kilo_entry,
        fmt="jsonc",
        default_scope="project",
    ),
    "cline": ClientDescriptor(
        project_path=cline_settings_path,
        global_path=cline_settings_path,
        top_key="mcpServers",
        entry_builder=_cline_entry,
        fmt="json",
        default_scope="project",
        merge_strategy="cline-global-storage",
    ),
    "qwen": ClientDescriptor(
        project_path=_project_relative(".qwen/settings.json"),
        global_path=_home_relative("~/.qwen/settings.json"),
        top_key="mcpServers",
        entry_builder=_base_entry,
        fmt="json",
        default_scope="project",
    ),
    "kimi": ClientDescriptor(
        # Global only (docs/MCP_SETUP.md) — no project-scoped config exists.
        project_path=_home_relative("~/.kimi/mcp.json"),
        global_path=_home_relative("~/.kimi/mcp.json"),
        top_key="mcpServers",
        entry_builder=_base_entry,
        fmt="json",
        default_scope="global",
    ),
}


def _jsonc_has_comments(text: str) -> bool:
    """True if ``text`` contains a ``//`` or ``/* */`` comment outside a
    JSON string (D4).

    A comment-free JSONC file is valid JSON and round-trips losslessly
    through ``json.loads``/``json.dumps``; only a file that genuinely has
    comments needs the print-fallback, so this is the only thing that
    decides which path ``write_client_config`` takes.
    """
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] in "/*":
            return True
        i += 1
    return False


def _manual_snippet(top_key: str, entry: dict[str, Any]) -> str:
    """The exact JSON to hand the user when a file can't be safely rewritten."""
    return json.dumps({top_key: {_SERVER_KEY: entry}}, indent=2)


class ClientWriteResult(NamedTuple):
    """Outcome of one ``write_client_config`` call.

    ``wrote`` is True only when THIS call wrote the file — mirrors
    ``InstallResult.changed``'s idempotent-rerun contract (a re-run reports
    False, no duplicate). ``needs_manual`` is True when the safe move was to
    leave the file untouched (a JSONC file with comments we cannot safely
    round-trip (D4), or Cline's extension globalStorage dir absent (D5)) — the
    caller must print ``snippet`` + ``path`` for the user to paste in by hand.
    """

    client: str
    path: Path
    wrote: bool
    top_key: str
    needs_manual: bool = False
    snippet: str | None = None


def write_client_config(client: str, scope: str | None = None) -> ClientWriteResult:
    """Write/merge the BrainPalace MCP server into ``client``'s config file.

    The non-Claude counterpart to ``install_mcp``: no approval or local-scope
    step (D7) — approval/trust is Claude-Code-specific plumbing, other clients
    trust their own config file. Just the file write, idempotent and never
    clobbering other keys/servers already in the file (A10-equivalent).

    ``scope`` picks project vs. global config; ``None`` defaults to the
    client's own ``default_scope``.

    JSON clients (D3): full idempotent deep-merge via ``merge_server``, write
    only if changed.

    JSONC clients — vscode, kilo (D4): if the file is absent or has no
    comments, merge and write normally (comment-free JSONC parses as plain
    JSON). If it has comments we cannot safely round-trip, do NOT rewrite —
    return ``wrote=False, needs_manual=True`` with the snippet to paste in by
    hand, so a user's JSONC comments are never corrupted.

    Cline (D5): its config lives inside a VS Code extension's globalStorage
    dir. If that dir does not exist (the extension is not installed), do NOT
    create it — return ``wrote=False, needs_manual=True`` instead of
    fabricating an uninstalled extension's storage.

    Raises ``ValueError`` for an unknown client, an unknown scope, or an
    existing file that cannot be parsed (never silently overwritten).
    """
    if client not in MCP_CLIENTS:
        raise ValueError(
            f"unknown client {client!r} — use one of {sorted(MCP_CLIENTS)}"
        )
    descriptor = MCP_CLIENTS[client]
    resolved_scope = scope or descriptor.default_scope
    if resolved_scope not in ("project", "global"):
        raise ValueError(f"unknown scope {resolved_scope!r} — use project or global")

    project_root = Path.cwd()
    path = (
        descriptor.global_path(project_root)
        if resolved_scope == "global"
        else descriptor.project_path(project_root)
    )
    entry = descriptor.entry_builder()

    if descriptor.merge_strategy == "cline-global-storage":
        # D5 — locate, don't fabricate: an uninstalled extension gets no dir.
        ext_dir = path.parent.parent
        if not ext_dir.exists():
            return ClientWriteResult(
                client,
                path,
                False,
                descriptor.top_key,
                needs_manual=True,
                snippet=_manual_snippet(descriptor.top_key, entry),
            )

    if descriptor.fmt == "jsonc" and path.exists():
        raw = path.read_text(encoding="utf-8")
        if _jsonc_has_comments(raw):
            # D4 — never corrupt a user's JSONC comments; print instead.
            return ClientWriteResult(
                client,
                path,
                False,
                descriptor.top_key,
                needs_manual=True,
                snippet=_manual_snippet(descriptor.top_key, entry),
            )

    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"Could not parse existing {path}: {e}") from e
        if not isinstance(existing, dict):
            raise ValueError(
                f"Existing {path} does not contain a JSON object at the top "
                "level — refusing to overwrite."
            )

    merged, changed = merge_server(existing, descriptor.top_key, _SERVER_KEY, entry)
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return ClientWriteResult(client, path, changed, descriptor.top_key)


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


#: --client choices, Claude first (it's the default and predates the rest).
_CLIENT_CHOICES = ["claude", *MCP_CLIENTS]


@click.command("install-mcp")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--no-approve",
    is_flag=True,
    help=(
        "Claude only: declare the server in .mcp.json but do not approve it. "
        "Claude Code will hold it at 'Pending approval' until you approve it "
        "yourself."
    ),
)
@click.option(
    "--client",
    type=click.Choice(_CLIENT_CHOICES),
    default="claude",
    show_default=True,
    help="Target MCP client to write the server entry for.",
)
@click.option(
    "--scope",
    type=click.Choice(["auto", "local", "project", "global"]),
    default=None,
    help=(
        "For --client claude: 'auto' (default), 'local', or 'project' — see "
        "below. For every other --client: 'project' or 'global', defaulting "
        "to that client's usual config location."
    ),
)
def install_mcp_command(
    json_output: bool, no_approve: bool, client: str, scope: str | None
) -> None:
    """Write BrainPalace's MCP server into an MCP client's config file.

    With the default ``--client claude``, merges a single
    ``mcpServers.brainpalace`` entry into any existing ``.mcp.json`` at the
    project root, preserving every other server already declared there.
    Idempotent: re-running does not duplicate or corrupt the file.

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

    With any other ``--client`` (cursor, windsurf, vscode, kilo, cline, qwen,
    kimi), writes/merges the server into that client's own config file
    instead — idempotently, never touching other keys or servers already
    there. These clients have no approval step of their own, so there is
    nothing further to grant. A JSONC file (vscode, kilo) that already has
    comments is never rewritten — the exact snippet to add by hand is printed
    instead, so your comments are never corrupted. Cline's config lives
    inside a VS Code extension's storage; if that extension is not installed,
    the snippet is printed instead of fabricating its directory.
    """
    if client == "claude":
        claude_scope = scope or "auto"
        if claude_scope not in ("auto", "local", "project"):
            _fail(
                json_output,
                f"--scope {claude_scope!r} is not valid for --client claude "
                "— use auto, local, or project.",
            )
        project_root = Path.cwd()
        try:
            result = install_mcp(
                project_root, approve=not no_approve, scope=claude_scope
            )
        except ValueError as e:
            _fail(json_output, str(e))

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
            click.echo(
                f"{verb} BrainPalace MCP server into {project_root / '.mcp.json'}"
            )
            if result.fallback_reason:
                click.echo(f"Local scope unavailable ({result.fallback_reason}).")
            if result.skip_reason:
                click.echo(f"Approval skipped: {result.skip_reason}")
            click.echo(notice)
        return

    if scope is not None and scope not in ("project", "global"):
        _fail(
            json_output,
            f"--scope {scope!r} is not valid for --client {client} — use "
            "project or global.",
        )

    try:
        write_result = write_client_config(client, scope)
    except ValueError as e:
        _fail(json_output, str(e))

    if json_output:
        payload = {
            "client": write_result.client,
            "path": str(write_result.path),
            "wrote": write_result.wrote,
            "top_key": write_result.top_key,
        }
        if write_result.needs_manual:
            payload["needs_manual"] = True
            payload["snippet"] = write_result.snippet
        click.echo(json.dumps(payload, indent=2))
    elif write_result.needs_manual:
        click.echo(f"Could not safely write {write_result.path} — add this by hand:")
        click.echo(write_result.snippet)
        click.echo(f"(path: {write_result.path})")
    else:
        status = "written" if write_result.wrote else "already up to date"
        console.print(
            Panel(
                f"[green]{write_result.client}: MCP config {status}.[/]\n\n"
                f"[bold]Target:[/] {write_result.path}",
                title=CLIENT_DISPLAY.get(write_result.client, write_result.client),
                border_style="green",
            )
        )


def _fail(json_output: bool, message: str) -> NoReturn:
    """Report an error the same way on both output channels and exit(1).

    Shared by both the Claude and generic-client branches so a bad
    ``--scope``/``--client`` combination or an unparseable existing file fails
    identically regardless of which path caught it.
    """
    if json_output:
        click.echo(json.dumps({"error": message}))
    else:
        click.echo(f"Error: {message}", err=True)
    raise SystemExit(1)

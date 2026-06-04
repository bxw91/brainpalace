---
last_validated: 2026-06-04
---

# MCP setup — connecting AI clients to BrainPalace

> **Opt-in.** BrainPalace ships an MCP server — `brainpalace mcp` — so
> non-Claude-Code AI clients can talk to BrainPalace with first-class typed
> tools instead of raw shell-outs. It is off by default; the Claude Code
> experience is unchanged.

The MCP server is a thin **stdio shim** over the existing BrainPalace HTTP server.
It does not replace the HTTP server — the HTTP server is still where queries,
indexing, and storage live; the MCP shim just forwards calls.

> ⚠️ **MCP client config formats drift between versions.** Snippets below are
> verified against the noted client versions at this file's authoring date.
> Re-verify against your client's current docs before publishing config to a
> team.

## Tool surface (v1 — read-only)

| Tool          | What it does                                                                                                |
| ------------- | ----------------------------------------------------------------------------------------------------------- |
| `query`       | Search indexed docs / code via BM25, vector, hybrid, graph, or multi-mode fusion.                           |
| `status`      | BrainPalace server health and indexing state.                                                               |
| `whoami`      | Resolve project root and server URL for a given path (or the MCP process CWD).                              |
| `folders_list`| List registered indexed folders with last-indexed timestamps.                                               |
| `jobs_list`   | List queued, running, and completed indexing jobs.                                                          |

Every tool except `whoami` accepts an optional **`path`** argument. Pass the
workspace or file path to override CWD-based server discovery — required for
multi-root workspaces or any editor that lets the user switch projects within a
single session. Without `path`, the long-lived MCP process is pinned to the
directory it was spawned in. `whoami` keeps the older `file_path` name.

### `query` parameters

| Parameter      | Type            | Default    | Description                                                   |
| -------------- | --------------- | ---------- | ------------------------------------------------------------- |
| `query`        | string          | —          | Search query text (required).                                 |
| `mode`         | string          | `"hybrid"` | Search mode: `bm25`, `vector`, `hybrid`, `graph`, `multi`.   |
| `top_k`        | integer         | `8`        | Number of results to return (1–100).                          |
| `languages`    | list of strings | `null`     | Filter results by programming language(s).                    |
| `source_types` | list of strings | `null`     | Filter results by source type(s).                             |
| `language`     | string          | `null`     | BM25 query language override (ISO 639-1, e.g. `"en"`, `"de"`, `"zh"`). Overrides the project `bm25.language` setting for this call only. Only affects BM25 tokenization — ignored for vector/graph modes. |
| `path`         | string          | `null`     | Resolve the server owning this path instead of the MCP process CWD. |

## The `--ensure-server` flag

The MCP shim **does not start the BrainPalace HTTP server** by default — Claude
Code has its own start hook, and we don't want to add a hidden side effect to
the shim. Every non-Claude-Code client snippet below includes
`--ensure-server` in its args: when set, the shim starts the HTTP server for
the spawn-time CWD project if discovery finds none. It never auto-runs
`brainpalace init` — an uninitialised project is left alone so the failure
stays explicit. Start failures are caught and logged to stderr so the MCP
handshake never hangs.

---

## Per-client setup

### Claude Code (opt-in)

Claude Code users typically prefer the **skill model** installed by the plugin
(`brainpalace query …` via slash commands). MCP here is for users who want
explicit typed tool calls instead of skill-mediated CLI.

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "brainpalace": {
      "command": "brainpalace",
      "args": ["mcp"]
    }
  }
}
```

The Claude Code plugin's start hook auto-starts the HTTP server, so
`--ensure-server` is not needed here.

A copy-paste-able fragment is also shipped at
`brainpalace-plugin/templates/mcp-config-claude-code.json`.

### VS Code (native MCP — GitHub Copilot agent mode)

VS Code has a **built-in MCP client**, separate from the Kilo Code / Cline /
Continue extensions below. It powers GitHub Copilot's agent mode. This is the
path for Copilot users, who otherwise have no way to reach BrainPalace (no
skill, no shell-out). It's the highest-reach client in this list.

```jsonc
// .vscode/mcp.json  (workspace-level; commit to share with the team)
{
  "servers": {
    "brainpalace": {
      "type": "stdio",
      "command": "brainpalace",
      "args": ["mcp", "--ensure-server"]
    }
  }
}
```

- Top-level key is `servers` — distinct from Claude Code / Cline (`mcpServers`)
  and Kilo (`mcp`).
- `type: "stdio"` for a local child process.
- User-level alternative: the `MCP: Add Server` command, or the `mcp` block in
  user `settings.json`.
- See the **VS Code extension users** section below for the PATH-inheritance
  gotcha that affects this client too.

### Cursor

Verified against Cursor's `mcp.json` format (early 2026).

```json
// ~/.cursor/mcp.json  (or per-project .cursor/mcp.json)
{
  "mcpServers": {
    "brainpalace": {
      "command": "brainpalace",
      "args": ["mcp", "--ensure-server"]
    }
  }
}
```

### Kilo Code (v7.x — verified 2026-05)

> Kilo Code changed its MCP config format in 7.x. The old Cline-derived
> `cline_mcp_settings.json` / `mcpServers` path is gone. If you used the older
> form, migrate.

Config files:

- Global: `~/.config/kilo/kilo.jsonc`
- Project: `kilo.jsonc` in project root, or `.kilo/kilo.jsonc`
- Project overrides global. Or use the UI: **Settings → MCP → Add Server →
  Local (stdio)**.

```jsonc
{
  "mcp": {
    "brainpalace": {
      "type": "local",
      "command": ["brainpalace", "mcp", "--ensure-server"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

Format notes vs the old Cline format:

- Top-level key is `mcp`, **not** `mcpServers`.
- `command` is a single array (executable + args); not split `command` + `args`.
- `type: "local"` is required for stdio servers.
- `enabled: true` replaces `disabled: false`.
- Env vars go in an `environment` object (not `env`); `{env:VAR}` syntax is
  supported.
- `timeout` is in milliseconds. Kilo's default for local servers is 10000 —
  too tight for a cold HTTP server or a `multi`-mode query. Set 30000.
  See [Troubleshooting](#troubleshooting).

### Cline

Cline retains the legacy `cline_mcp_settings.json` / `mcpServers` format that
Kilo abandoned — the two are **no longer the same JSON**. Re-verify against
current Cline docs before publishing. Legacy starting point:

```json
{
  "mcpServers": {
    "brainpalace": {
      "command": "brainpalace",
      "args": ["mcp", "--ensure-server"],
      "disabled": false
    }
  }
}
```

### Continue

```yaml
# .continue/mcp.yaml or per-project equivalent
mcpServers:
  - name: brainpalace
    command: brainpalace
    args: ["mcp", "--ensure-server"]
```

### Zed

```json
// .zed/settings.json
{
  "context_servers": {
    "brainpalace": {
      "command": {
        "path": "brainpalace",
        "args": ["mcp", "--ensure-server"]
      }
    }
  }
}
```

---

## VS Code extension users — environment gotcha (Kilo Code, Cline, Continue, Roo)

This applies to every MCP client that runs as a VS Code extension, and to
Cursor.

### 1. PATH inheritance

VS Code (and Cursor) launched from a GUI launcher / dock does **not** inherit
your shell's `PATH` on Linux and macOS. The extension spawns the MCP child
with VS Code's own process environment. If `brainpalace` lives in a Poetry
venv, a pipx shim, or `~/.local/bin`, then `"command": "brainpalace"` fails
with `ENOENT` — *"server failed to start"*.

Fixes, most robust first:

- **Absolute path.** Run `which brainpalace` in a real shell, use the full
  path as the first array element:
  ```json
  "command": ["/home/you/.local/bin/brainpalace", "mcp", "--ensure-server"]
  ```
- **Inject PATH.** Add the bin dir via the client's env field — Kilo's
  `environment`, Cline's `env`.
- **Launch the editor from a terminal** (`code .`) so it inherits the shell
  PATH.

### 2. The HTTP server

The MCP shim only forwards calls — it doesn't host anything. Pass
`--ensure-server` in the client args (as shown above) so the shim auto-starts
the HTTP server for your workspace project on first connect. Without
`--ensure-server`, you must run `brainpalace start` in the project (integrated
terminal, or as a background service) before MCP tools work.

### 3. Working directory

Tool discovery walks up from the MCP process's CWD looking for
`.brainpalace/runtime.json`. VS Code extensions normally spawn the child with
CWD = workspace root, which is correct for a single-root project.

Multi-root workspaces and mid-session project switches are not handled by CWD
alone — pass the `path` argument on tool calls, or treat one editor window as
one project.

---

## Troubleshooting

- **"Server failed to start"** → `brainpalace` not resolvable in the editor's
  env. Use an absolute path (`which brainpalace`), or inject PATH via the
  client's `environment` / `env` field. See the env gotcha above.
- **"No tools listed"** → the MCP shim started but the handshake or SDK failed;
  check the client's MCP log.
- **"Tool calls return 'no brainpalace server running'"** → either run
  `brainpalace start` in the project root manually, or add `--ensure-server`
  to the client args.
- **"Tool calls time out"** → raise the client's per-call timeout. Kilo's
  default `timeout` is `10000` ms; bump to `30000`. Cold servers and
  `multi`-mode queries are slow on first hit (graph index load can be
  500 MB – 1 GB).
- **"Queries return results from the wrong project"** → CWD coupling. The MCP
  process is pinned to its spawn-time directory. Pass `path` on the tool
  call, or use one editor window per project.

---

## What this MCP server does NOT do (v1)

- **No mutation tools.** `index`, `index_inject`, `reset`, `folders_add`,
  `folders_remove` are deferred. v1 is read-only so the blast radius is
  bounded.
- **No authentication.** Local stdio only. A future streamable-HTTP transport
  will need auth.
- **No idle timeout.** stdio servers stay alive as long as the client keeps
  them connected. Most MCP clients spawn one process per workspace and reap on
  disconnect.
- **No auto-init.** `--ensure-server` will not run `brainpalace init` for you.
  Initialise the project (`brainpalace init`) before connecting MCP clients.

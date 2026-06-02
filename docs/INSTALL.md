---
last_validated: 2026-05-30
---

# Install — alternative paths

The [README](../README.md#install) ships the **guided installer**
(`setup.sh`) as the one-command path. This file collects everything
else: manual step-by-step installs, non-interactive flows, install
for other AI runtimes, and the low-level `install.sh` invocation.

Most users do not need anything in here. Use it only if the guided
installer is the wrong tool for your situation (CI, locked-down
environments, custom orchestration, audit requirements).

---

## Adding more projects after the first install

The `brainpalace` binary is installed **once per machine** (in your
pipx venv). Every project gets its own server, on its own
auto-allocated port, with its own `.brainpalace/` state directory.

**Three commands per new project:**

```bash
cd /path/to/other-project
brainpalace init --start --watch auto    # writes .brainpalace/, starts server, enrols watcher
brainpalace index .                       # code + docs (default)
```

Then query as usual — `brainpalace` walks up from CWD to find the
right server for whichever project you happen to be in:

```bash
brainpalace query "how does auth work" --mode hybrid
```

**Inspect all your running projects:**

```bash
brainpalace list           # all live servers across the machine
brainpalace whoami         # which project owns the current dir
brainpalace status         # current project's server + index health
```

**Stop a specific project's server:**

```bash
cd /path/to/that-project && brainpalace stop
# or by URL from `brainpalace list`:
brainpalace stop --url http://127.0.0.1:49321
```

### Reusing the provider config

Two ways to avoid re-running `brainpalace config wizard` per project:

1. **Copy** an existing `.brainpalace/config.yaml` into the new
   project's `.brainpalace/` after `init`. Provider, model, graphrag,
   and api_key_env all carry over. The exported API key in your shell
   rc covers all projects on the same machine.
2. **Run the guided installer again.** Re-running
   `curl -sSL …/scripts/setup.sh | bash` is safe: step 1 detects the
   binary already installed and asks before reinstalling, so you only
   pay the prompt cost — the rest of the wizard sets up the new
   project from scratch (provider, init, index, MCP-client wiring).

### Wiring an MCP client to multiple projects

Each MCP-client config points at one project (its CWD at spawn time).
If your editor opens different projects in different windows, that is
usually enough — one window = one project. For multi-root or
mid-session project switches, pass the `path` argument on each MCP
tool call (the shim accepts it on every tool except `whoami`). See
[`MCP_SETUP.md`](MCP_SETUP.md) for the multi-root caveat.

---

## Manual CLI install (four steps)

Skips `setup.sh`. Run each command in order.

1. **Install the `brainpalace` binary** (one line — installs
   `brainpalace-cli` via pipx, which pulls the `brainpalace-rag` server
   into the same venv):

   ```bash
   curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash
   ```

   Verify: `brainpalace --version` → `26.5.1` or newer.

2. **Initialise the project + start the server** (writes
   `.brainpalace/` config + state, launches the HTTP server in the
   background, registers it for discovery):

   ```bash
   cd /path/to/your/project
   brainpalace init --start
   ```

   > Equivalent to `brainpalace init` + `brainpalace start`. Add
   > `--watch auto` to also enrol the project root in the file
   > watcher so edits reindex automatically.

3. **Index your code + docs** (server starts empty; nothing is
   searchable until you index):

   ```bash
   brainpalace index .                  # code + docs (default)
   brainpalace index ./docs --no-code   # docs only
   ```

4. **Query:**

   ```bash
   brainpalace query "authentication" --mode hybrid
   ```

`brainpalace` auto-discovers the project root by walking up from CWD
to the nearest `.brainpalace/runtime.json` — no `--url` flag needed,
mono-repo safe.

---

## Manual MCP install (four steps)

For AI clients that speak MCP — Cursor, VS Code (GitHub Copilot agent
mode), Cline, Continue, Kilo Code, Zed. The MCP shim is a thin
forwarder over the same REST endpoints the CLI uses.

1. **Install the `brainpalace` binary:**

   ```bash
   curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash
   ```

2. **Initialise the project + start the server:**

   ```bash
   cd /path/to/your/project
   brainpalace init --start
   ```

3. **Wire your AI client.** Minimal VS Code (Copilot agent mode)
   example:

   ```jsonc
   // .vscode/mcp.json   (workspace-level; commit to share with team)
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

   `--ensure-server` auto-starts the HTTP server for the spawn-time
   project if discovery finds none — covers the case where you skip
   step 2 and rely on the MCP client to bring the server up on first
   tool call.

4. **Index** (skip if step 2 already enrolled the project in the
   watcher with `--watch auto`):

   ```bash
   brainpalace index .
   ```

Per-client snippets for Cursor, Cline, Continue, Kilo Code, Zed, and
an opt-in Claude Code MCP config — plus the VS Code PATH-inheritance
gotcha that bites Cursor too — live in [`MCP_SETUP.md`](MCP_SETUP.md).

Read-only v1 tool surface: `query`, `status`, `whoami`, `folders_list`,
`jobs_list`.

---

## Non-interactive shells (CI, no TTY)

`setup.sh` reads from `/dev/tty` so `curl … | bash` works in any
interactive shell. If your environment has no TTY (some CI runners),
either use the manual four-step install above, or download `setup.sh`
first and feed it a TTY some other way:

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/setup.sh -o /tmp/ab-setup.sh
bash /tmp/ab-setup.sh
```

For purely scripted CI, prefer the manual `install.sh` + explicit
`brainpalace init/start/index` commands — easier to gate, log, and
retry per step.

---

## Install for other AI runtimes

`brainpalace install-agent` converts the canonical Claude Code plugin
layout into the target runtime's native format. Run after the binary
is installed:

```bash
brainpalace install-agent --agent codex
brainpalace install-agent --agent opencode
brainpalace install-agent --agent gemini
brainpalace install-agent --agent skill-runtime --dir ./my-skills

# Preview only:
brainpalace install-agent --agent codex --dry-run
```

Full reference: [USER_GUIDE.md → Runtime installation](USER_GUIDE.md#runtime-installation).

---

## `install.sh` flags (low level)

`setup.sh` calls `install.sh` for the binary install. If you want
just the binary install (no init / no index / no MCP wiring):

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash
```

Flags:

| Flag | Meaning |
|---|---|
| `--version <ver>` | Pin to a PyPI version |
| `--local <path>` | Install from a local checkout |
| `--dry-run` | Print actions, change nothing |

---

## Manual `pipx` invocation and Windows

`pipx` covers the same ground as `install.sh`. Windows is WSL2-only for
now (a native PowerShell installer is planned).

```bash
pipx install brainpalace-cli
```

`brainpalace-cli` pulls the `brainpalace-rag` server into the same venv.

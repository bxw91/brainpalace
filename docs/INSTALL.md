---
last_validated: 2026-07-23
---

# Install — alternative paths

> **Using Claude Code? The recommended path is the plugin** — it installs the
> CLI + server for you and summarizes your sessions for free on your Claude Code
> subscription (no separate API bill — draws on your subscription's usage limits):
> `claude plugins marketplace add bxw91/brainpalace && claude plugins install brainpalace@brainpalace-marketplace`
> (then restart Claude Code). See [README → Install](../README.md#install). The
> guided `setup.sh` also **offers the plugin first** when Claude Code is present.

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

**One command per new project:**

```bash
cd /path/to/other-project
brainpalace init        # confirm, then: write .brainpalace/, start server,
                        # index docs (watch=auto), back up + embed chat sessions
```

`brainpalace init` sets up the project and **backs up chat sessions locally (free)**
by default. An interactive run then **asks before the two session features**, each
tagged with the real provider it uses:

- **Summarize chat sessions?** `[Y/n]` — free, runs on the Claude Code Haiku subagent
  (`→ Claude Code Haiku (subscription)`); makes past chats searchable by topic.
- **Embed chat sessions too?** `[y/N]` — **opt-in, billable**; sends transcript content
  to your embedding provider (`→ OpenAI text-embedding-3-large`) for full-text semantic
  recall. Default **no** — summaries already cover the common case.

Opt out / preset non-interactively:

| Flag | Effect |
|------|--------|
| `--no-start` | write config only — no server, no indexing |
| `--no-watch` | start the server but do not register/index the folder |
| `--sessions` | embed chat sessions (opt into the billable step) |
| `--no-sessions` | never embed chat sessions |
| `--no-extract` | never summarize chat sessions |
| `--no-archive` | do not keep the raw transcript backup |
| `--yes` / `-y` | non-interactive: archive + summarize, **no embedding** (add `--sessions` to embed) |

In a non-interactive context (CI, piped, `--json`) a bare `brainpalace init`
stays config-only — it never starts. `--yes` runs the setup but **does not embed
chat sessions** unless `--sessions` is also passed.

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

> **Claude Code users can skip this.** Step 2 below (`brainpalace init
> --start`) already writes the project's `.mcp.json` by default (`--no-mcp`
> to opt out) and registers the server with Claude Code, which needs no
> approval; an already-initialized project adopts it with `brainpalace
> install-mcp`. Restart Claude Code to pick the tools up. See
> [`MCP_SETUP.md`](MCP_SETUP.md#claude-code-opt-in-automatic-per-project).

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

MCP tool surface (12 tools): the read-only core — `query`, `status`, `whoami`,
`folders_list`, `jobs_list`, `recall`, `session_context`, `ai_guide`,
`extraction_fetch` — plus write tools `memorize`, `extraction_submit`, and
`jobs_approve` (the last spends embedding tokens and requires explicit consent).

---

## Non-interactive shells (CI, no TTY)

`setup.sh` reads from `/dev/tty` so `curl … | bash` works in any
interactive shell. If your environment has no TTY (some CI runners),
either use the manual four-step install above, or download `setup.sh`
first and feed it a TTY some other way:

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/setup.sh -o /tmp/bp-setup.sh
bash /tmp/bp-setup.sh
```

For purely scripted CI, prefer the manual `install.sh` + explicit
`brainpalace init/start/index` commands — easier to gate, log, and
retry per step.

---

## Install for other AI runtimes

**The guided installer already covers this.** After the binary installs,
`setup.sh` offers a multi-select — "Wire AI coding assistants for this
project?" — over Claude, Codex, OpenCode, Antigravity, Qwen Code, Kimi CLI,
and skill-runtime; pick any combination in one run. Claude gets the
timeout-guarded marketplace install; Codex/OpenCode/Antigravity/skill-runtime
get project-scoped `install-agent` runs; **Qwen Code and Kimi CLI get BOTH** —
`install-agent` (skills) **and** `install-mcp --client` (MCP) — since they
speak both. That's the recommended path; this section is the manual
low-level command for wiring one runtime by hand, without re-running the
wizard.

`brainpalace install-agent` converts the canonical Claude Code plugin
layout into the target runtime's native format. Run after the binary
is installed:

```bash
brainpalace install-agent --agent codex
brainpalace install-agent --agent opencode
brainpalace install-agent --agent antigravity
brainpalace install-agent --agent qwen     # .qwen/skills/brainpalace + QWEN.md
brainpalace install-agent --agent kimi     # .kimi-code/skills/brainpalace + AGENTS.md
brainpalace install-agent --agent skill-runtime --dir ./my-skills

# Qwen and Kimi also speak MCP — wire that half too:
brainpalace install-mcp --client qwen
brainpalace install-mcp --client kimi

# Preview only:
brainpalace install-agent --agent codex --dry-run
```

### Initialising a project, per environment

Install once (`setup.sh`, or the manual steps above), pick your assistant(s),
then init **per project** in whichever environment you're using:

| Environment | Init command |
|---|---|
| Claude Code | `/brainpalace-init` (slash command; also wires per-project MCP) |
| Codex / OpenCode / Antigravity | Ask the assistant to initialise, or run `brainpalace init` in the terminal — the agents shell out to the CLI |
| CLI / terminal | `brainpalace init` |

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

---

## Updating

One command — auto-detects pipx / uv / pip and runs the matching upgrade:

```bash
brainpalace update          # add --yes to skip the confirm
```

Then restart any running server so it loads the new code:

```bash
brainpalace stop && brainpalace start
```

Plugin files (`.claude/plugins/...`) don't auto-update — refresh with
`brainpalace install-agent --agent <runtime>`. Manual equivalents per manager:
`pipx upgrade brainpalace-cli` / `uv tool upgrade brainpalace-cli` /
`pip install --upgrade brainpalace-rag brainpalace-cli`.

---

## Full uninstall (teardown)

Uninstalling the package alone does **not** remove BrainPalace. State is left in
project directories, global XDG dirs, MCP client configs, and your shell rc.

### Guided uninstall (recommended)

If the CLI is still installed, the guided teardown is one command:

```bash
brainpalace uninstall
```

It confirms each step — stop servers, remove plugin dirs (all runtimes/scopes),
strip the `brainpalace` entry from MCP configs (keeping your other servers),
delete selected per-project state, delete global state — then **prints the
leftover steps**: for pip installs the final `pip uninstall …` line (a process
can't delete its own running env; pipx/uv it offers to run for you), and the
shell-rc API key (left to you — it may be shared with other tools).

If the binary is **already gone** (or you prefer pure bash / curl), use the
script mirror of `setup.sh`:

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/uninstall.sh | bash
```

Both leave your shell rc alone. Prefer the manual steps below for full control.

### Manual teardown

Run these steps **in order** — enumerate and stop servers *before* removing the
binary, or you lose the tool that lists them.

#### 1. Stop every running server

```bash
brainpalace list                       # show all running servers + their projects
brainpalace stop --path <project>      # repeat per project (or run from each dir)
```

`pipx uninstall` does not stop daemons; skipping this leaves orphan `uvicorn`
processes.

#### 2. Note the projects, then remove the plugin from each runtime

Record the project list from `brainpalace list` first — you need it in step 4.

There is **no CLI command to remove an installed plugin** (`install-agent` only
installs). Delete the install dirs directly — per runtime, project scope **and**
global scope:

```bash
rm -rf .claude/plugins/brainpalace    ~/.claude/plugins/brainpalace
rm -rf .opencode/plugins/brainpalace  ~/.config/opencode/plugins/brainpalace
rm -rf .agents/skills/brainpalace     ~/.gemini/config/skills/brainpalace
rm -rf .codex/skills/brainpalace      ~/.codex/skills/brainpalace
rm -rf .qwen/skills/brainpalace       ~/.qwen/skills/brainpalace
rm -rf .kimi-code/skills/brainpalace  ~/.kimi-code/skills/brainpalace
```

(Run the project-scope paths from each project root; the `~/...` paths are the
global installs.)

> **Installed via the Claude Code plugin marketplace instead?** Those skills live
> under `~/.claude/plugins/cache/<marketplace>/brainpalace` and are tracked by
> Claude Code's own registry — **don't `rm` that cache** (it desyncs
> `installed_plugins.json`). Remove it from Claude Code: run `/plugin` → uninstall
> "brainpalace" (and optionally the "brainpalace-marketplace"). The guided
> `brainpalace uninstall` detects this and prints the same instruction.

#### 3. Uninstall the package

| Method | Command |
|--------|---------|
| pipx | `pipx uninstall brainpalace-cli` |
| uv | `uv tool uninstall brainpalace-cli` |
| pip | `pip uninstall brainpalace-rag brainpalace-cli -y` |
| conda | `pip uninstall brainpalace-rag brainpalace-cli -y` (inside the env), then `conda env remove -n brainpalace` |

> **Pick the row that matches how you installed.** The official installer uses
> **pipx** — `which brainpalace` pointing at `…/pipx/venvs/…` means you want the
> pipx row, not pip. A bare `pip uninstall` against a Debian/Ubuntu **system**
> Python (3.12+) fails with `error: externally-managed-environment` (PEP 668);
> for a genuine system-pip install, re-run it with `--break-system-packages`.

#### 4. Delete per-project state — ⚠️ contains raw session transcripts

Every initialised project has a `.brainpalace/` holding the index, logs, config,
**and archived raw chat transcripts (full user turns — may include secrets).**
There is one per project (use the list from step 1/2):

```bash
rm -rf <project>/.brainpalace          # repeat for every project
```

#### 5. Delete global state (XDG dirs + legacy)

Respect `$XDG_CONFIG_HOME` / `$XDG_STATE_HOME` / `$XDG_DATA_HOME` if you set them;
otherwise the defaults are:

```bash
rm -rf ~/.config/brainpalace           # config.yaml (global)
rm -rf ~/.local/state/brainpalace      # registry.json (tracks all projects)
rm -rf ~/.local/share/brainpalace      # data (if present)
rm -rf ~/.brainpalace                  # legacy pre-XDG dir (if present)
```

#### 6. Remove MCP client config entries

`brainpalace init`/`install-mcp`, or `setup.sh`, may have written a
`brainpalace` server entry (with an absolute path to the now-deleted binary)
into any of these. Delete the entry or the file:

```
.mcp.json            .vscode/mcp.json     .cursor/mcp.json
.zed/settings.json   .cline/mcp.json      .continue/mcp.yaml   .kilo/kilo.jsonc
.qwen/settings.json  ~/.kimi/mcp.json
```

`.mcp.json` (Claude Code) is project scope only. The rest can live at project
scope **and** at `$HOME` (user scope) — check both. Kimi is global-only
(`~/.kimi/mcp.json`, listed above with the full path since there is no
project-scope variant).

#### 7. Revert shell rc + PATH

- Remove any `export OPENAI_API_KEY=…` (or other provider key) you added on
  setup.sh's advice.
- `pipx` added its bin dir to `PATH` via `pipx ensurepath`; remove that line if
  BrainPalace was the only pipx tool.

After step 7, `command -v brainpalace` should print nothing and no `.brainpalace/`
or `*/brainpalace` directories remain.

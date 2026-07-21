---
last_validated: 2026-07-18
---

# BrainPalace Quick Start

Get up and running with BrainPalace in minutes: **install once, pick your AI
assistant(s), then init each project you work in.**

## Step 1: Install (one command)

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/setup.sh | bash
```

This is the guided installer — interactive, asks before every action:

1. Installs the `brainpalace` binary (CLI + server, via pipx)
2. Offers the Claude Code plugin as a free chat-summary engine, if `claude` is on PATH
3. Configures your embedding/summarization provider globally (OpenAI, Anthropic,
   Cohere, Gemini, Grok, or local Ollama)
4. Optionally sets up + indexes a project — **and offers a multi-select to wire
   your AI coding assistant(s)** (skills runtimes + MCP editors, in one merge-safe
   step), see Step 2
5. Verifies with `brainpalace status` and a sample query

Prefer manual control, scripted CI, or no TTY? See [`INSTALL.md`](INSTALL.md)
for the step-by-step path (same install.sh under the hood).

## Step 2: Pick your assistant(s)

During Step 4 of the installer, answer **"Wire AI coding assistants for this
project?"** with a comma-separated pick — any combination, in one run:

| Pick | Installs |
|---|---|
| Claude Code | The plugin, via the marketplace (global) — 43 commands, 6 agents, 2 skills |
| Codex | `.codex/skills/brainpalace/` + `AGENTS.md` |
| OpenCode | `.opencode/plugins/brainpalace/` |
| Antigravity (agy) | `.agents/skills/brainpalace/` + `AGENTS.md` |
| Qwen Code | `.qwen/skills/brainpalace/` + `QWEN.md`, **and** MCP (`.qwen/settings.json`) |
| Kimi CLI | `.kimi-code/skills/brainpalace/` + `AGENTS.md`, **and** MCP (`~/.kimi/mcp.json`) |
| Generic skill-runtime | SKILL.md files in a directory you choose |
| Cursor / Windsurf / VS Code / Kilo / Cline | MCP config via `install-mcp --client <name>` |

Wiring a runtime outside the wizard — later, or for a project you skipped —
run `install-agent` directly:

```bash
brainpalace install-agent --agent codex
brainpalace install-agent --agent opencode
brainpalace install-agent --agent antigravity
brainpalace install-agent --agent qwen      # + brainpalace install-mcp --client qwen
brainpalace install-agent --agent kimi      # + brainpalace install-mcp --client kimi
brainpalace install-agent --agent skill-runtime --dir ./my-skills
```

Claude Code's plugin also installs from inside Claude Code (`/plugin`, add
marketplace `bxw91/brainpalace`, install `brainpalace`) or directly:
`claude plugins marketplace add bxw91/brainpalace && claude plugins install
brainpalace@brainpalace-marketplace`.

See the [User Guide](USER_GUIDE.md#runtime-installation) for full runtime
installation details.

## Step 3: Initialize each project

Install once, pick your assistant(s) once — then **init per project**, in
whichever environment you're using:

| Environment | Init command |
|---|---|
| Claude Code | `/brainpalace-init` (slash command; also wires per-project MCP) |
| Codex / OpenCode / Antigravity | Ask the assistant to initialise, or run `brainpalace init` in the terminal — the agents shell out to the CLI |
| CLI / terminal | `brainpalace init` |

`brainpalace init` writes `.brainpalace/`, starts the server, and indexes the
project by default (confirm each step interactively, or `--yes` to run
non-interactively). Re-index specific paths or file types any time:

```
/brainpalace-index ./docs                          # docs only
/brainpalace-index .                                # code + docs
/brainpalace-index ./src --include-type python      # file-type presets
```

Manage indexed folders explicitly:

```
/brainpalace-folders add ./src
/brainpalace-folders add ./docs
/brainpalace-folders list
```

Check indexing status:

```
/brainpalace-status
```

## Step 4: Search Your Knowledge Base

Now you can search! Use the query command (hybrid mode by default):

```
/brainpalace-query "how does authentication work"
```

Or pick a specific search mode with `--mode`:

```
/brainpalace-query --mode vector "explain the architecture"
/brainpalace-query --mode bm25 "getUserById"
/brainpalace-query --mode graph "what calls AuthService"
```

---

## Step 5: Connect via MCP (optional)

**Claude Code**: `brainpalace init` already wrote a per-project `.mcp.json` and
registered the server with Claude Code (unless you passed `--no-mcp`), so this
is done — restart Claude Code to get typed `query`/`status`/… tool calls
alongside the slash commands. No approval step: the registration goes in your
own `~/.claude.json`, not the repo. Skipped it, or initialized before this
existed? `brainpalace install-mcp` wires it up without re-running `init`.

Other AI clients — VS Code native (GitHub Copilot agent mode), Cursor, Kilo
Code, Cline, Continue, Zed — can call BrainPalace through the Model Context
Protocol too. BrainPalace ships an opt-in stdio shim:

```bash
brainpalace mcp --ensure-server   # auto-starts the HTTP server if not live
```

Clients spawn this as a child process and speak MCP over stdin/stdout. The
shim is a thin forwarder over the same REST endpoints used by the CLI; no
extra service to deploy. Per-client config snippets (and the VS Code
PATH-inheritance gotcha that bites Cursor too) live in
[`MCP_SETUP.md`](MCP_SETUP.md).

---

## Already in Claude Code? Use the plugin wizard instead

If Claude Code is your only assistant, its guided plugin wizard mirrors
`setup.sh`'s flow through slash commands — install, configure, init, start,
index — and offers the same multi-runtime assistant wiring:

```
/brainpalace-setup
```

For everything else — CLI-only use, multiple assistants, CI — `setup.sh`
(Step 1 above) is the canonical path.

---

## Search Modes Quick Reference

| Command | Best For | Example |
|---------|----------|---------|
| `/brainpalace-query` | General questions | "how does caching work" |
| `/brainpalace-query --mode vector` | Conceptual queries | "explain the data flow" |
| `/brainpalace-query --mode bm25` | Exact terms, errors | "NullPointerException" |
| `/brainpalace-query --mode hybrid --alpha 0.7` | Fine-tuned search | "API authentication" |
| `/brainpalace-query --mode graph` | Dependencies | "what uses UserService" |
| `/brainpalace-query --mode multi` | Maximum recall | "everything about validation" |

---

## Using Agents for Complex Tasks

For complex research tasks, BrainPalace's intelligent agents help:

**You**: "Research how error handling is implemented across the codebase"

**Research Assistant** automatically:
1. Searches documentation for error handling patterns
2. Queries code for try/catch blocks and error classes
3. Uses graph mode to find error propagation
4. Synthesizes a comprehensive answer with file references

---

## Verify Your Setup

Check that everything is working:

```
/brainpalace-verify
```

This validates:
- Package installation
- API key configuration
- Server connectivity
- Index health

Or run the CLI diagnostic directly (works in scripts — exits non-zero on
any critical failure):

```bash
brainpalace doctor          # full report
brainpalace doctor --fix    # also apply safe, offline fixes
```

---

## Next Steps

- [User Guide](USER_GUIDE.md) - Detailed usage patterns
- [Plugin Guide](PLUGIN_GUIDE.md) - All 43 commands documented
- [Provider Configuration](../brainpalace-plugin/skills/using-brainpalace/references/provider-configuration.md) - Configure embedding and summarization providers

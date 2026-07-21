---
name: brainpalace-install-agent
description: Install BrainPalace plugin for a specific runtime (Claude, OpenCode, Codex, Antigravity, Qwen Code, Kimi CLI, skill-runtime)
parameters:
  - name: agent
    type: choice
    required: true
    default: ""
  - name: project
    type: bool
    required: false
    default: project
  - name: global
    type: bool
    required: false
    default: ""
  - name: plugin-dir
    type: directory
    required: false
    default: ""
  - name: dir
    type: path
    required: false
    default: ""
  - name: dry-run
    type: bool
    required: false
    default: false
  - name: json
    type: bool
    required: false
    default: false
  - name: path
    type: directory
    required: false
    default: ""
skills:
  - configuring-brainpalace
last_validated: 2026-07-21
---

# BrainPalace Install Agent

## Purpose

Installs BrainPalace plugin files for a specific AI coding runtime. Converts the canonical plugin format into the target runtime's native format and writes the files to the appropriate directory.

Supported runtimes:
- **Claude Code** — copies plugin as-is with path normalization
- **OpenCode** — converts tool lists to boolean objects, maps tool names to lowercase
- **Codex** — creates skill directories under `.codex/skills/brainpalace/` and generates AGENTS.md
- **Antigravity (agy)** — mirrors Codex exactly: skill directories under `.agents/skills/brainpalace/` + AGENTS.md; no tool-name remap
- **Qwen Code** — mirrors Codex: skill directories under `.qwen/skills/brainpalace/` + `QWEN.md` (not AGENTS.md); also has an MCP client (`install-mcp --client qwen`) — dual
- **Kimi CLI** — mirrors Codex: skill directories under `.kimi-code/skills/brainpalace/` + AGENTS.md; also has an MCP client (`install-mcp --client kimi`) — dual
- **skill-runtime** — generic converter producing skill directories with SKILL.md frontmatter (requires `--dir`)

## Usage

```
brainpalace install-agent --agent <runtime> [--project|--global] [--plugin-dir <path>] [--dir <path>] [--dry-run] [--json] [--path <path>]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --agent / -a | Yes | - | Target runtime: `claude`, `opencode`, `codex`, `antigravity`, `qwen`, `kimi`, or `skill-runtime` |
| --project | No | Yes | Install to project directory (default) |
| --global | No | No | Install to user-level directory |
| --plugin-dir | No | Auto-detect | Custom canonical plugin source directory |
| --dir | No* | - | Target skill directory (*required for skill-runtime) |
| --dry-run | No | No | List files without writing |
| --json | No | No | Machine-readable JSON output |
| --path / -p | No | cwd | Project path for --project scope |

### Install Directories

<!--GENERATED:install-dirs-->
| Runtime | Project dir | Global dir |
|---------|-------------|------------|
| `claude` | `.claude/plugins/brainpalace` | `~/.claude/plugins/brainpalace` |
| `opencode` | `.opencode/plugins/brainpalace` | `~/.config/opencode/plugins/brainpalace` |
| `codex` | `.codex/skills/brainpalace` | `~/.codex/skills/brainpalace` |
| `antigravity` | `.agents/skills/brainpalace` | `~/.gemini/config/skills/brainpalace` |
| `qwen` | `.qwen/skills/brainpalace` | `~/.qwen/skills/brainpalace` |
| `kimi` | `.kimi-code/skills/brainpalace` | `~/.kimi-code/skills/brainpalace` |
<!--/GENERATED-->

`skill-runtime` has no fixed install dir — it requires `--dir /path/to/skills`.

## Execution

### Install for Claude Code (default)

```bash
brainpalace install-agent --agent claude --project
```

### Install for OpenCode

```bash
brainpalace install-agent --agent opencode --project
```

### Install for Codex

```bash
brainpalace install-agent --agent codex --project
```

This creates skill directories under `.codex/skills/brainpalace/` and generates an `AGENTS.md` file at the project root.

### Install for Antigravity

```bash
brainpalace install-agent --agent antigravity --project
```

This mirrors Codex exactly: skill directories under `.agents/skills/brainpalace/` and an `AGENTS.md` file at the project root.

### Install for Qwen Code

```bash
brainpalace install-agent --agent qwen --project
```

This mirrors Codex, but generates `QWEN.md` (not `AGENTS.md`) at the project root — Qwen Code's hierarchical memory file. Qwen also speaks MCP: `brainpalace install-mcp --client qwen`.

### Install for Kimi CLI

```bash
brainpalace install-agent --agent kimi --project
```

This mirrors Codex exactly: skill directories under `.kimi-code/skills/brainpalace/` and an `AGENTS.md` file at the project root. Kimi also speaks MCP (separate config under `~/.kimi/`): `brainpalace install-mcp --client kimi`.

### Install for Generic Skill-Runtime

```bash
brainpalace install-agent --agent skill-runtime --dir ./my-skills
```

The `--dir` flag is required for skill-runtime (it has no default directory).

### Global Installation

```bash
brainpalace install-agent --agent claude --global
```

### Preview Without Installing

```bash
brainpalace install-agent --agent claude --dry-run
```

### JSON Output

```bash
brainpalace install-agent --agent claude --json
```

### Custom Plugin Source

```bash
brainpalace install-agent --agent opencode --plugin-dir ./my-custom-plugin
```

## Output

### Normal Output

```
╭──────── BrainPalace Installed ────────╮
│ Plugin installed successfully!         │
│                                        │
│ Runtime: claude                        │
│ Scope:   project                       │
│ Target:  .claude/plugins/brainpalace/  │
│ Files:   12                            │
╰────────────────────────────────────────╯
```

### Dry Run Output

```
╭──────── Install Preview ────────╮
│ Dry run — no files written       │
│                                  │
│ Runtime: claude                  │
│ Scope:   project                 │
│ Target:  .claude/plugins/...     │
│ Files:   12                      │
╰──────────────────────────────────╯
  .claude/plugins/brainpalace/commands/brainpalace-search.md
  .claude/plugins/brainpalace/agents/search-assistant.md
  ...
```

### JSON Output

```json
{
  "status": "installed",
  "agent": "claude",
  "scope": "project",
  "target_dir": ".claude/plugins/brainpalace",
  "files_created": 12,
  "source_dir": "/path/to/canonical/plugin"
}
```

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Could not find canonical plugin directory | Plugin source not found | Use `--plugin-dir` to specify location |
| Invalid agent choice | Unsupported runtime name | Use `claude`, `opencode`, `codex`, `antigravity`, `qwen`, `kimi`, or `skill-runtime` |
| --dir is required for --agent skill-runtime | Missing target directory | Specify `--dir ./path/to/skills` |

## Notes

- All runtimes share the same `.brainpalace/` data directory for indexes and configuration
- The canonical plugin format uses YAML frontmatter + markdown body
- Runtime converters handle tool name mapping and format differences automatically
- Use `--dry-run` to preview changes before installing

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --agent | choice | "" | Target runtime to install for |
| --project | bool | project | Install to project directory (default) |
| --global | bool | "" | Install to user-level directory |
| --plugin-dir | directory | "" | Custom canonical plugin source directory |
| --dir | path | "" | Target skill directory (required for skill-runtime) |
| --dry-run | bool | false | List files that would be created without writing |
| --json | bool | false | Output as JSON |
| --path | directory | "" | Project path for --project scope (default: cwd) |
<!--/GENERATED-->

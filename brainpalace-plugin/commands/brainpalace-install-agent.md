---
name: brainpalace-install-agent
description: Install BrainPalace plugin for a specific runtime (Claude, OpenCode, Gemini)
parameters:
  - name: agent
    description: "Target runtime: claude, opencode, gemini, skill-runtime, or codex"
    required: true
  - name: scope
    description: "Install scope: project (default) or global"
    required: false
    default: project
  - name: plugin-dir
    description: Custom canonical plugin source directory
    required: false
  - name: dir
    description: Target skill directory (required for skill-runtime)
    required: false
  - name: dry-run
    description: List files that would be created without writing
    required: false
  - name: json
    description: Output as JSON
    required: false
  - name: path
    description: "Project path for --project scope (default: cwd)"
    required: false
skills:
  - configuring-brainpalace
last_validated: 2026-05-30
---

# BrainPalace Install Agent

## Purpose

Installs BrainPalace plugin files for a specific AI coding runtime. Converts the canonical plugin format into the target runtime's native format and writes the files to the appropriate directory.

Supported runtimes:
- **Claude Code** — copies plugin as-is with path normalization
- **OpenCode** — converts tool lists to boolean objects, maps tool names to lowercase
- **Gemini CLI** — remaps tool names (e.g., Bash->run_shell_command), removes unsupported fields
- **Codex** — creates skill directories under `.codex/skills/brainpalace/` and generates AGENTS.md
- **skill-runtime** — generic converter producing skill directories with SKILL.md frontmatter (requires `--dir`)

## Usage

```
brainpalace install-agent --agent <runtime> [--project|--global] [--plugin-dir <path>] [--dir <path>] [--dry-run] [--json] [--path <path>]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --agent / -a | Yes | - | Target runtime: `claude`, `opencode`, `gemini`, `skill-runtime`, or `codex` |
| --project | No | Yes | Install to project directory (default) |
| --global | No | No | Install to user-level directory |
| --plugin-dir | No | Auto-detect | Custom canonical plugin source directory |
| --dir | No* | - | Target skill directory (*required for skill-runtime) |
| --dry-run | No | No | List files without writing |
| --json | No | No | Machine-readable JSON output |
| --path / -p | No | cwd | Project path for --project scope |

### Install Directories

| Runtime | Project Scope | Global Scope |
|---------|---------------|--------------|
| Claude | `.claude/plugins/brainpalace/` | `~/.claude/plugins/brainpalace/` |
| OpenCode | `.opencode/plugins/brainpalace/` | `~/.config/opencode/plugins/brainpalace/` |
| Gemini | `.gemini/plugins/brainpalace/` | `~/.config/gemini/plugins/brainpalace/` |
| Codex | `.codex/skills/brainpalace/` | `~/.codex/skills/brainpalace/` |
| skill-runtime | Requires `--dir` | Requires `--dir` |

## Execution

### Install for Claude Code (default)

```bash
brainpalace install-agent --agent claude --project
```

### Install for OpenCode

```bash
brainpalace install-agent --agent opencode --project
```

### Install for Gemini CLI

```bash
brainpalace install-agent --agent gemini --project
```

### Install for Codex

```bash
brainpalace install-agent --agent codex --project
```

This creates skill directories under `.codex/skills/brainpalace/` and generates an `AGENTS.md` file at the project root.

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
| Invalid agent choice | Unsupported runtime name | Use `claude`, `opencode`, `gemini`, `skill-runtime`, or `codex` |
| --dir is required for --agent skill-runtime | Missing target directory | Specify `--dir ./path/to/skills` |

## Notes

- All runtimes share the same `.brainpalace/` data directory for indexes and configuration
- The canonical plugin format uses YAML frontmatter + markdown body
- Runtime converters handle tool name mapping and format differences automatically
- Use `--dry-run` to preview changes before installing

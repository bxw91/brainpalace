---
name: brainpalace-ai-guide
description: Print canonical AI usage guidance (search modes, query rules, gotchas)
parameters:
  - name: tier
    type: choice
    required: false
    default: full
  - name: format
    type: choice
    required: false
    default: markdown
skills:
  - using-brainpalace
last_validated: 2026-07-10
---

# BrainPalace AI Guide

## Purpose

Prints the canonical AI-facing BrainPalace usage guidance — search modes, the
non-negotiable search rule, the `--json` result contract, and server-down
behavior — from the single source of truth
(`brainpalace_cli/data/ai_guidance.md`).

This is the **pull** path for agents that have neither the Claude plugin skill
nor the MCP `instructions=` block (e.g. a CLI-only external agent). The same
source generates the `using-brainpalace` SKILL.md, feeds the MCP server's
`instructions=` (CORE tier) and `ai_guide` tool, and the SessionStart hook
(NUDGE tier). Editing it in one place updates every surface — enforced by
`task lint:ai-guidance-parity`.

## Usage

```
/brainpalace:brainpalace-ai-guide [--tier nudge|core|full] [--format markdown|hook|mcp|skill]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --tier | No | full | `nudge` (one-line reminder), `core` (decision contract), `full` (everything) |
| --format | No | markdown | `markdown`/`hook`/`mcp` emit the tier text; `skill` emits the full SKILL.md |

## Execution

### Full guidance (default)

```bash
brainpalace ai-guide
```

### Just the decision contract

```bash
brainpalace ai-guide --tier core
```

### Regenerate the plugin skill (maintainers)

```bash
brainpalace ai-guide --format skill > brainpalace-plugin/skills/using-brainpalace/SKILL.md
```

## Notes

- `--format skill` is the authoritative way to regenerate `SKILL.md`; never
  hand-edit that file (the parity gate fails on drift).
- Output is English-only and byte-deterministic (`version`/`last_validated` come
  from the source, not the current date).

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-search` | Run a search using the guidance below |
| `/brainpalace:brainpalace-status` | Verify the server before searching |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --tier | choice | full | nudge = minimal reminder; core = decision contract; full = everything. |
| --format | choice | markdown | markdown/hook/mcp emit the tier text; skill emits the full SKILL.md. |
<!--/GENERATED-->

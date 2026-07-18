---
name: brainpalace-doctor
description: Diagnose your BrainPalace setup (Python, config, keys, server reachability)
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: json
    type: bool
    required: false
    default: false
  - name: fix
    type: bool
    required: false
    default: false
  - name: reap
    type: bool
    required: false
    default: false
  - name: "yes"
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-07-18
---

# BrainPalace Doctor

## Purpose

Diagnoses your BrainPalace setup. It inspects the Python version, project init
state, provider config, required API keys, optional dependencies, `.gitignore`
hygiene, and whether the server is reachable. It exits non-zero on any critical
failure so it can be used in scripts (e.g. `brainpalace doctor || brainpalace init`).

Pass `--fix` to auto-apply the safe subset of remediations and re-run. Pass
`--reap` to first kill orphan (unreferenced) server processes that may be holding
ports.

## Usage

```
/brainpalace:brainpalace-doctor [--url <url>] [--json] [--fix] [--reap]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --url | No | from runtime.json or config | Server URL to probe |
| --json | No | false | Emit machine-readable JSON |
| --fix | No | false | Apply safe, idempotent, offline fixes (gitignore, state dir, stub config), then re-run. Never touches API keys, network, or user code |
| --reap | No | false | Kill orphan server processes not referenced by a live registry entry, before running diagnostics |

## Execution

```bash
brainpalace doctor
```

Auto-apply safe fixes and re-check:

```bash
brainpalace doctor --fix
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-init` | Initialize a new project |
| `/brainpalace:brainpalace-status` | Check server status and health |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | Server URL to probe (default: resolved from runtime.json or config). |
| --json | bool | false | Emit machine-readable JSON. |
| --fix | bool | false | Apply safe, idempotent, offline fixes (add .brainpalace/ to .gitignore, create state dir + stub config.yaml). Will not touch API keys, network, or user code. Re-runs the report after fixing. |
| --reap | bool | false | Kill orphan server processes not referenced by a live registry entry (leaked servers that hold ports). Runs before the diagnostics. |
| --yes | bool | false | Auto-install missing LSP servers without prompting. |
<!--/GENERATED-->

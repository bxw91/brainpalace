---
name: brainpalace-update
description: Upgrade BrainPalace (CLI + server + dashboard) to the latest version
parameters:
  - name: "yes"
    type: bool
    required: false
    default: false
  - name: no-restart
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-19
---

# BrainPalace Update

## Purpose

Upgrades BrainPalace (CLI + server + dashboard) to the latest version. It
auto-detects pipx / uv / pip. The default flow is **stop-all → upgrade →
restart-and-verify**: every running instance is stopped first (so the upgrade can
never silently leave old code serving), then the same set is restarted one by one
with a per-instance health check. If the upgrade fails, you are told loudly that
nothing is running and you are NOT on the new version.

Use `--no-restart` to upgrade without touching running instances.

## Usage

```
/brainpalace:brainpalace-update [--yes] [--no-restart]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --yes, -y | No | false | Skip confirmation prompt |
| --no-restart | No | false | Upgrade only — leave running instances untouched (they keep serving OLD code until restarted) |

## Execution

```bash
brainpalace update
```

Upgrade without restarting running servers:

```bash
brainpalace update --no-restart
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-doctor` | Diagnose the setup after upgrading |
| `/brainpalace:brainpalace-status` | Verify the server is healthy |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --yes | bool | false | Skip confirmation prompt |
| --no-restart | bool | false | Upgrade only — leave running instances untouched (they keep serving OLD code until you restart them yourself). |
<!--/GENERATED-->

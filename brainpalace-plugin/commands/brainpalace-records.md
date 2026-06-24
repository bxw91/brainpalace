---
name: brainpalace-records
description: Manage typed numeric records (compute mode) — stats and revalidation
parameters:
skills:
  - using-brainpalace
last_validated: 2026-06-23
---

# BrainPalace Records

## Purpose

Manages the typed numeric record store used by the `compute` query mode.
Exposes two subcommands: `stats` (shows total records, unverified count, and
distinct metric names) and `revalidate` (re-scores low-confidence records,
optionally filtered to a single metric).

## Usage

```
/brainpalace:brainpalace-records <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| stats | Show record store statistics (total, unverified, metrics) |
| revalidate | Re-score low-confidence records (confidence < 0.7) |

## Execution

```bash
brainpalace records stats
brainpalace records revalidate
brainpalace records revalidate --metric bodyweight
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-query` | Search with `--mode compute` to aggregate over records |
| `/brainpalace:brainpalace-status` | Check the server is healthy |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
<!--/GENERATED-->

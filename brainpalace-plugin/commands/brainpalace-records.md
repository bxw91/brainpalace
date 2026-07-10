---
name: brainpalace-records
description: Manage typed numeric records (compute mode) — stats, revalidation, salience recompute
parameters:
skills:
  - using-brainpalace
last_validated: 2026-07-05
---

# BrainPalace Records

## Purpose

Manages the typed numeric record store used by the `compute` query mode.
Exposes three subcommands: `stats` (shows total records, unverified count, and
distinct metric names), `revalidate` (re-scores low-confidence records,
optionally filtered to a single metric), and `recompute-salience` (re-scores the
derived salience column via the registered scorer, optionally filtered to a
single metric).

## Usage

```
/brainpalace:brainpalace-records <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| stats | Show record store statistics (total, unverified, metrics) |
| revalidate | Re-score low-confidence records (confidence < 0.7) |
| recompute-salience | Re-score the derived salience column via the registered scorer |

## Execution

```bash
brainpalace records stats
brainpalace records revalidate
brainpalace records revalidate --metric bodyweight
brainpalace records recompute-salience
brainpalace records recompute-salience --metric bodyweight
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-query` | Search with `--mode compute` to aggregate over records |
| `/brainpalace:brainpalace-status` | Check the server is healthy |

### Flags
<!--GENERATED:flags-->
_This command takes no top-level flags._
<!--/GENERATED-->

---
name: brainpalace-rules
description: Manage durable taught confidence rules (compute-mode trust)
parameters:
skills:
  - using-brainpalace
last_validated: 2026-07-05
---

# BrainPalace Rules

## Purpose

Manages durable, taught confidence rules for the `compute` query mode's typed
records. A rule declares that records matching a metric (and optionally a unit
and a `[value_min, value_max]` range) should be scored at a given confidence
tier (`HIGH`, `PROVISIONAL`, or `UNVERIFIED`) instead of the default
numeric-sanity baseline. Rules persist in the server's `rules.db` and are
reloaded on every server start, so a taught rule survives restart. At most one
rule is active per `owner + metric + unit`; adding a rule for a combination
that already has an active rule retires the old one and bumps the version —
an edit, not a parallel rule. `retire` soft-deletes a rule (history is kept).
Adding or retiring a rule immediately re-scores that metric's existing records.

## Usage

```
/brainpalace:brainpalace-rules <subcommand>
```

### Subcommands

| Subcommand | Description |
|------------|-------------|
| list | List taught rules (active by default; `--all` includes retired) |
| add | Teach a confidence rule for a metric (promotes matching records) |
| retire | Retire (soft-delete) a taught rule by id |
| show | Show one taught rule by id |

## Execution

```bash
brainpalace rules add --metric weight --unit kg --min 30 --max 300 --tier HIGH
brainpalace rules list
brainpalace rules list --all
brainpalace rules show <rule_id>
brainpalace rules retire <rule_id>
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-records` | Record store stats, revalidate, and recompute-salience |
| `/brainpalace:brainpalace-query` | Search with `--mode compute` to aggregate over records |

### Flags
<!--GENERATED:flags-->
_This command takes no top-level flags._
<!--/GENERATED-->

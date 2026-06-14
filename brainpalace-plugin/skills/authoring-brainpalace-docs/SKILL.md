---
name: authoring-brainpalace-docs
description: |
  Use when `brainpalace sync-docs --fix` reports PROSE-NEEDED, or when a new
  command/skill/mode needs its human prose (Purpose, Examples) written. Authoring
  playbook for interface docs whose machine regions are generated.
license: MIT
last_validated: 2026-06-14
metadata:
  version: 1.0.0
allowed-tools:
  - Bash
  - Read
  - Edit
---

# Authoring BrainPalace interface docs

The deterministic generator owns the **machine regions** (frontmatter `parameters:`,
`GENERATED:*` blocks). You write the **human prose** only — never edit inside a
`GENERATED:` block.

## Flow
1. Run `brainpalace sync-docs --fix`. It regenerates machine regions and prints
   `PROSE-NEEDED: <id> -> <doc> (<reason>)` for anything that needs prose.
2. For each PROSE-NEEDED item, open the doc and write, **outside** any GENERATED block:
   - `## Purpose` — one short paragraph from `brainpalace <cmd> --help` (what it does,
     not why). Use only flags/behavior that actually exist.
   - `### Examples` — 1–3 real invocations.
3. Write prose **only where it is missing or dangling** — do not reword existing valid
   prose (keeps commits churn-free).
4. Re-run `brainpalace sync-docs --check` until it prints `doc-sync: OK`.

## Rules
- Never invent flags/commands/modes — verify against `--help` / `sync-docs --check`.
- Never edit inside `<!--GENERATED:…-->` blocks (the generator overwrites them).
- English only; match the surrounding docs' tone.

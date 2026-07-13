---
name: brainpalace-rehome
description: Show or resume the project-move rehome quarantine
skills:
  - using-brainpalace
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: resume
    type: bool
    required: false
    default: false
  - name: json
    type: bool
    required: false
    default: false
last_validated: 2026-07-13
---

# Rehome

## Purpose

Shows, or resumes, the project-move rehome quarantine. When an indexed project
directory is moved, the server auto-detects the move on next start and repairs
all path-addressed stores (folder records, manifest keys, chunk metadata, the
sqlite graph, the reference catalog) via a checkpointed prefix-swap — no
re-embedding. While that rehome is mid-run or failed, the server is
fail-closed: it 503s everything except health and rehome routes.

Bare `rehome` reports the current quarantine state (`quarantined`, `status`,
`reason`). `--resume` drives a pending/failed rehome to completion from its
checkpoint in place, without restarting the server (a restart also
auto-resumes it — `--resume` is for unblocking a server that is already
running). `--resume` when nothing is pending is not an error: it reports "no
rehome pending".

### Examples

```
/brainpalace:brainpalace-rehome
/brainpalace:brainpalace-rehome --resume
/brainpalace:brainpalace-rehome --json
```

## Usage

```
/brainpalace:brainpalace-rehome [--url <url>] [--resume] [--json]
```

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Connection error | Server is not running | Run `brainpalace start` — it also auto-resumes any pending rehome on boot |
| Quarantined (status shown) | Project directory was moved and rehoming has not completed | Run `brainpalace rehome --resume`, or just restart the server |

## Notes

- Nested moves (`/a/b` → `/a/b/c`) are refused rather than rehomed — run
  `brainpalace reset` and re-index instead.
- A project moved before this feature shipped cannot be repaired retroactively
  (the prior root is unknown); the current location is adopted as the new
  baseline.
- There is no dashboard panel for this command: a quarantined server 503s the
  dashboard's own proxied API, so recovery is inherently CLI/restart-driven.

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config) |
| --resume | bool | false | Resume a pending/failed rehome from its checkpoint |
| --json | bool | false | Output as JSON |
<!--/GENERATED-->

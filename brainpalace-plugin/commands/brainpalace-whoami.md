---
name: brainpalace-whoami
description: Show which BrainPalace project and server own the current directory
parameters:
  - name: file
    type: path
    required: false
    default: ""
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-13
---

# BrainPalace Whoami

## Purpose

Shows which BrainPalace project and server own the current directory. It walks up
from the current directory (or the `--file` path) to the owning project's
`.brainpalace/` directory, then reports the project root and its running server.

Exit codes:
- `0` — project found with a live server
- `1` — no project found
- `2` — project found but the server is not running

## Usage

```
/brainpalace:brainpalace-whoami [--file <path>] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --file | No | current directory | Resolve ownership for this file/path instead of the CWD |
| --json | No | false | Output as JSON |

## Execution

```bash
brainpalace whoami
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-status` | Check server status and health |
| `/brainpalace:brainpalace-list` | List all running instances |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --file | path | "" | Resolve ownership for this file/path instead of the current directory |
| --json | bool | false | Output as JSON |
<!--/GENERATED-->

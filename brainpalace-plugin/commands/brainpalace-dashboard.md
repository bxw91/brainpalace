---
name: brainpalace-dashboard
description: Launch, stop, or inspect the BrainPalace web control-plane dashboard
parameters:
context: brainpalace
agent: setup-assistant
skills:
  - using-brainpalace
last_validated: 2026-07-10
---

# BrainPalace Dashboard

## Purpose

Launches the BrainPalace **web control plane** — a standalone dashboard that
manages every BrainPalace project server from one browser tab:

- List / start / stop / restart project-server instances
- Edit all config via click-only batched forms
- View real stats, jobs, cache, graph, sessions, logs
- Browse query history (with live replay)

The dashboard runs as its own process (default port **8787**, scanning upward to
8887) with a dedicated runtime pidfile (`dashboard.json` under the XDG state
dir), separate from per-project servers. It works with zero servers running —
the Instances/Overview/Config tabs are server-independent.

## Usage

```
/brainpalace:brainpalace-dashboard [start|stop|status] [--host <host>] [--port <port>] [--foreground] [--no-open] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| action | No | start | `start`, `stop`, or `status` |
| --host | No | 127.0.0.1 | Bind host (overrides config; start only) |
| --port | No | 8787 (scans upward) | Preferred port (start only) |
| --foreground, -f | No | false | Run in foreground (start only) |
| --no-open | No | false | Do not open a browser (start only) |
| --json | No | false | Output as JSON |

## Execution

### Start the dashboard

```bash
# Launch and open a browser at http://127.0.0.1:8787/dashboard/
brainpalace dashboard start

# Pick a port (scans upward if busy)
brainpalace dashboard start --port 8900

# Launch without opening a browser (e.g. on a server)
brainpalace dashboard start --no-open

# Run in the foreground for debugging
brainpalace dashboard start --foreground
```

### Check status

```bash
brainpalace dashboard status
brainpalace dashboard status --json
```

### Stop the dashboard

```bash
brainpalace dashboard stop
```

## Output

### Successful Start

```
BrainPalace Dashboard running
URL: http://127.0.0.1:8787/dashboard/

Next steps:
  - Open the URL above in a browser
  - Stop: brainpalace dashboard stop
```

### Status (running)

```
Dashboard running
URL: http://127.0.0.1:8787/dashboard/
PID: 12345
Port: 8787
Health: healthy
```

## Configuration

The dashboard reads its `dashboard:` section from the canonical XDG config
(`~/.config/brainpalace/config.yaml`):

```yaml
dashboard:
  host: "127.0.0.1"   # bind host
  port: 8787          # preferred port (scans upward)
  poll_s: 5           # SPA polling interval (seconds)
  token: null         # optional bearer token (see Security)
```

## Security

The dashboard binds to `127.0.0.1` (localhost) and is **unguarded by default** —
intended for single-user local machines. On a shared host, set a bearer token to
require `Authorization: Bearer <token>` on `/dashboard/api/**`:

```bash
export BRAINPALACE_DASHBOARD_TOKEN="my-secret"   # or dashboard.token in config
brainpalace dashboard start
```

`/dashboard/api/health` and static assets remain open. The dashboard is
CLI-launched and is **not** an MCP surface.

## Installation note

The dashboard is included with the CLI automatically on **Python 3.12+** (it
carries a `python >= 3.12` marker, so it's skipped on 3.10/3.11 — the CLI still
installs). If it isn't present, the command prints a friendly install hint. In a
source checkout, `task install` installs it automatically.

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-start` | Start a project server |
| `/brainpalace:brainpalace-list` | List running instances |
| `/brainpalace:brainpalace-status` | Check a project server's status |
| `/brainpalace:brainpalace-config` | Edit configuration |

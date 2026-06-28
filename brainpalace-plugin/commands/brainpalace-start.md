---
name: brainpalace-start
description: Start the BrainPalace server for this project
parameters:
  - name: path
    type: directory
    required: false
    default: ""
  - name: host
    type: text
    required: false
    default: ""
  - name: port
    type: integer
    required: false
    default: ""
  - name: foreground
    type: bool
    required: false
    default: false
  - name: timeout
    type: integer
    required: false
    default: 120
  - name: json
    type: bool
    required: false
    default: false
  - name: strict
    type: bool
    required: false
    default: false
  - name: no-dashboard
    type: bool
    required: false
    default: false
  - name: no-activate
    type: bool
    required: false
    default: false
context: brainpalace
agent: setup-assistant
skills:
  - using-brainpalace
last_validated: 2026-06-24
---

# BrainPalace Start

## Purpose

Starts the BrainPalace server for the current project. The server provides:
- Document indexing and storage
- Hybrid, semantic, and keyword search
- Multi-instance support with automatic port allocation

## Usage

```
/brainpalace:brainpalace-start [--path <dir>] [--host <host>] [--port <port>] [--foreground] [--strict] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --path, -p | No | auto-detect | Project path |
| --host | No | 127.0.0.1 | Server bind host (overrides config) |
| --port | No | auto-select (8000-8100) | Server port (overrides config) |
| --foreground, -f | No | false | Run in foreground (don't daemonize) |
| --timeout | No | 120 | Startup timeout in seconds |
| --strict | No | false | Fail on critical provider config errors |
| --no-dashboard | No | false | Do not auto-start the web dashboard (overrides `dashboard.autostart`) |
| --json | No | false | Output as JSON |

## Execution

### Pre-flight Check

Verify the project is initialized:

```bash
# Check for .brainpalace/ directory
ls -la .brainpalace/
```

If not initialized:
```bash
brainpalace init
```

### Start Server

```bash
# Start in background (default, recommended)
brainpalace start

# Start on a specific port
brainpalace start --port 8080

# Start in foreground for debugging
brainpalace start --foreground

# Start with strict mode (fail on missing API keys)
brainpalace start --strict

# Start for a specific project path
brainpalace start --path /my/project

# JSON output for scripting
brainpalace start --json
```

### Verify Server Started

```bash
brainpalace status
```

## Output

### Successful Start

```
BrainPalace Server Running
URL: http://127.0.0.1:8000
PID: 12345
Project: ~/my-project
Log: ~/my-project/.brainpalace/logs/server.log

Next steps:
  - Query: brainpalace query 'search term' --url http://127.0.0.1:8000
  - Stop: brainpalace stop
```

### JSON Output

```json
{
  "status": "started",
  "base_url": "http://127.0.0.1:8000",
  "pid": 12345,
  "project_root": "~/my-project",
  "log_file": "~/my-project/.brainpalace/logs/server.log"
}
```

### Runtime Configuration

The server creates a runtime file (in the state directory) with:

```json
{
  "schema_version": "1.0",
  "mode": "project",
  "project_root": "~/my-project",
  "instance_id": "a1b2c3d4e5f6",
  "base_url": "http://127.0.0.1:8000",
  "bind_host": "127.0.0.1",
  "port": 8000,
  "pid": 12345,
  "started_at": "2026-01-31T10:30:00+00:00"
}
```

This file enables automatic server discovery for CLI commands.

## Error Handling

### Project Not Initialized

```
Error: Project not initialized at ~/my-project
Run 'brainpalace init' to initialize the project.
```

**Resolution**:
```bash
brainpalace init
brainpalace start
```

### Server Already Running

If a server is already running for this project, the command reports the existing URL instead of starting a new one:

```
Server Running
Server already running!
URL: http://127.0.0.1:8000
PID: 12345
Project: ~/my-project
```

**Resolution**:
- Use the existing server, or
- Stop and restart: `brainpalace stop && brainpalace start`

### No Available Port

```
Error: No available port in range 8000-8100
```

**Resolution**: Specify a port explicitly or stop other instances:
```bash
brainpalace start --port 9000
# or
brainpalace list --all
brainpalace stop
```

### Missing API Keys

The server starts even without API keys, but provider-dependent features will be unavailable. Use `--strict` to force failure on missing keys.

**Resolution**: Set the API key via config file or environment variable and restart.

**Option 1: Config file** (`.brainpalace/config.yaml` or `~/.config/brainpalace/config.yaml`):
```yaml
embedding:
  provider: "openai"
  api_key_env: "OPENAI_API_KEY"
```

**Option 2: Environment variable**:
```bash
export OPENAI_API_KEY="sk-proj-..."
```

Then restart:
```bash
brainpalace stop
brainpalace start
```

### Permission Denied

```
Permission Error: [Errno 13] Permission denied: ...
```

**Resolution**:
```bash
mkdir -p .brainpalace
chmod 755 .brainpalace
brainpalace start
```

## Post-Start Tasks

### 1. Verify Server Health

```bash
brainpalace status
```

### 2. Index Documents (if first time)

```bash
# Index documentation
brainpalace index docs/

# Index code with type preset
brainpalace index src/ --include-type python
```

### 3. Test Search

```bash
brainpalace query "test query" --mode hybrid
```

## Server Behavior

### Project Root Resolution

The server auto-detects the project root by:
1. Git repository root (`git rev-parse --show-toplevel`)
2. Walking up looking for `.brainpalace/` directory
3. Walking up looking for `.claude/` directory
4. Walking up looking for `pyproject.toml`
5. Falling back to current working directory

### Port Allocation

By default, `auto_port` is enabled and the server finds an available port in the 8000-8100 range. Override with `--port` or disable auto-port in `config.json`.

### Stale State Cleanup

If a previous server died without cleanup, `brainpalace start` automatically detects and cleans up stale state before starting.

### Registry

Each started server is registered in the global registry (`~/.local/state/brainpalace/registry.json`) so `brainpalace list` can discover all instances.

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-init` | Initialize project for BrainPalace |
| `/brainpalace:brainpalace-status` | Check server status |
| `/brainpalace:brainpalace-stop` | Stop the server |
| `/brainpalace:brainpalace-list` | List all running instances |

## Troubleshooting

### Server Won't Start

1. Check for existing processes:
   ```bash
   ps aux | grep brainpalace
   ```

2. Check port availability:
   ```bash
   lsof -i :8000
   ```

3. Check logs:
   ```bash
   cat .brainpalace/logs/server.log
   cat .brainpalace/logs/server.err
   ```

### Server Crashes on Start

1. Verify Python environment:
   ```bash
   which python
   python --version  # Should be 3.10+
   ```

2. Verify installation:
   ```bash
   pip show brainpalace-rag brainpalace-cli
   ```

3. Check for dependency issues:
   ```bash
   pip check
   ```

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --path | directory | "" | Project path (default: auto-detect project root) |
| --host | text | "" | Server bind host (overrides config) |
| --port | integer | "" | Server port (overrides config) |
| --foreground | bool | false | Run in foreground (don't daemonize) |
| --timeout | integer | 120 | Startup timeout in seconds (default: 120) |
| --json | bool | false | Output as JSON |
| --strict | bool | false | Enable strict mode: fail on critical provider configuration errors |
| --no-dashboard | bool | false | Do not bring up the web dashboard from this server, by any path (overrides dashboard.autostart; also stops the server's self-heal from re-spawning one for its lifetime) |
| --no-activate | bool | false | Internal: do NOT clear the activation marker (cli.await_first_start). Passed by passive callers (the SessionStart hook) so only a genuine manual start activates a deferred project. |
<!--/GENERATED-->

---
last_validated: 2026-06-15
---

# Web Dashboard

The **BrainPalace dashboard** is a standalone web control plane that manages
every BrainPalace project server from a single browser tab. It is launched and
managed entirely through the CLI (`brainpalace dashboard`), runs on its own
fixed base port (default **8787**), and discovers per-project servers
dynamically.

> The dashboard is a **CLI-launched web surface**, not an MCP server. MCP
> clients connect to per-project servers via `brainpalace mcp` — see
> [MCP_SETUP.md](MCP_SETUP.md).

---

## Quick start

```bash
# Launch the dashboard and open it in a browser
brainpalace dashboard start

# Check whether it's running / healthy
brainpalace dashboard status

# Stop it
brainpalace dashboard stop
```

`start` opens `http://127.0.0.1:8787/dashboard/` in your default browser. Use
`--no-open` to skip the browser, or `--foreground` to run uvicorn in the
foreground for debugging.

### Command reference

| Command | Description |
|---------|-------------|
| `brainpalace dashboard start` | Launch the dashboard (scan 8787→8887), write its pidfile, open a browser |
| `brainpalace dashboard stop` | SIGTERM the running dashboard and clear its runtime |
| `brainpalace dashboard status` | Report whether the dashboard is running and healthy |

`start` flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind host (overrides config) |
| `--port` | `8787` | Preferred port; scans upward to 8887 if busy |
| `--foreground`, `-f` | off | Run in the foreground (blocks; no browser opened) |
| `--no-open` | off | Do not open a browser after starting |
| `--json` | off | Emit machine-readable JSON |

---

## Port model

- **Dashboard:** a fixed base port, **8787**, scanning upward to **8887** if
  8787 is taken. The chosen port and PID are recorded in a dedicated runtime
  pidfile, `dashboard.json`, under the XDG state dir
  (`$XDG_STATE_HOME/brainpalace/dashboard.json`, default
  `~/.local/state/brainpalace/dashboard.json`). This is separate from the
  project-server `registry.json`.
- **Project servers:** keep their own **dynamic** ports (8000–8100 range). The
  dashboard discovers running servers from `registry.json` and keeps a durable
  list of every project it has seen, so **stopped instances stay listed and
  Start-able** even when no server is running.

---

## Server self-registration & heal

Discovery does not depend on *how* a server was launched. Every running project
server **registers itself**: a request-path middleware learns the real bound
address from the ASGI socket and writes its own `runtime.json` plus its
`registry.json` entry off the response path, and a 180-second heartbeat
re-asserts that registration. So a server started by raw `uvicorn`, an IDE, or
left orphaned still shows up in the dashboard — no CLI bookkeeping required.

The same heartbeat self-heals the server's in-process dependents: it restarts a
dead **file watcher** or **job worker** (worker restarts are capped), rebuilds a
**corrupt vector index** (crash-safe, file-only check), and relaunches the
**web dashboard** if it is down (locked so multiple project servers launch it
exactly once). On clean shutdown the server deregisters itself.

---

## Tabs

The left rail is the page switcher. It has a **Server** entry (the control
plane) at the top and the list of **instances** below. Selecting **Server**
shows the server page (and only its tabs); selecting an instance shows that
instance's page (and only its tabs). The two tab sets never mix.

**Server page** (control plane)

| Tab | What it shows |
|-----|---------------|
| **Overview** | Aggregate stats across all instances |
| **Instances** | List / start / stop / restart every project server (server-independent; works with zero servers up) |
| **Settings** | The dashboard's **own** (control-plane) config — `host`/`port`/`poll_s`/`token` in the `dashboard:` block of the XDG `config.yaml`. Distinct from per-instance Config. `host`/`port`/`token` apply on the next `brainpalace dashboard` restart; `poll_s` on reload. |

**Instance page** (selected instance)

| Tab | What it shows |
|-----|---------------|
| **Status** | The full `brainpalace status` view for the selected instance — version, documents (code/doc), chunks (code/doc), indexing state, indexed folder paths, last indexed, file watcher, session archive/memory/summarization, embedding cache (entries + hit rate + hits/misses), graph index (store + entities/rels), LSP, git index, BM25 language/engine |
| **Config** | Edit that instance's `config.yaml` via click-only batched forms generated from the config schema |
| **Folders** | Indexed folders (add / remove / watch state) |
| **Queries** | Query history (≥2 days) with detail and live replay |
| **Jobs** | Background job queue |
| **Cache** | Embedding-cache status and clear |
| **Graph** | GraphRAG entities / relationships |
| **Sessions** | Session archive + memory/index state and actions |
| **Logs** | Tail of `.brainpalace/server.log` (shows a graceful "unavailable" note if the server predates the log endpoint) |

Per-instance data tabs (Status/Folders/Queries/Jobs/Cache/Graph/Sessions/Logs)
proxy to a live server and show a clean "stopped — Start" state when it's down.
The Fleet tabs (Overview/Instances/Settings) and the per-instance Config tab are
server-independent. Every mutating action (save, start/stop/restart, remove,
clear, reset, delete, re-index, …) prompts for confirmation.

---

## Configuration

The dashboard reads its `dashboard:` section from the canonical XDG config file
(`~/.config/brainpalace/config.yaml`). All keys are optional:

```yaml
dashboard:
  host: "127.0.0.1"   # bind host
  port: 8787          # preferred port (scans upward to 8887)
  poll_s: 5           # SPA polling interval, seconds
  token: null         # optional bearer token (see Security)
```

The **Queries** tab surfaces the server's query history, which is governed by the
per-project `query_log:` section of each project's `config.yaml`:

```yaml
query_log:
  enabled: true        # record queries to .brainpalace/query_log.db
  retention_days: 7    # how long to keep query records
```

(`QUERY_LOG_ENABLED=false` is a kill switch.) See
[CONFIGURATION.md](CONFIGURATION.md) for the full config reference.

---

## Security

The dashboard binds to **localhost (`127.0.0.1`)** and is **unguarded by
default** — it is designed for single-user local machines.

On a **shared host**, enable a bearer token. When a token is configured, every
request to `/dashboard/api/**` must carry `Authorization: Bearer <token>`;
`/dashboard/api/health` and static assets stay open.

```bash
export BRAINPALACE_DASHBOARD_TOKEN="my-secret"
brainpalace dashboard start
# or, persistently, set dashboard.token in ~/.config/brainpalace/config.yaml
```

The token is resolved from the `BRAINPALACE_DASHBOARD_TOKEN` env var first, then
`dashboard.token` in config.

---

## Performance — the polling model

The SPA is deliberately frugal with network traffic. Fleet liveness and
per-tab data use two different mechanisms:

- **One SSE stream for fleet state.** The shell opens a *single*
  `EventSource` to `GET /dashboard/api/events` (see
  `frontend/src/state/useLiveInstances.ts`). The server emits an `instances`
  event roughly every 5 s (`poll_s`), and each frame is pushed straight into
  the shared TanStack Query `["instances"]` cache. Every tab that shows fleet
  state (Overview, Instances, the sidebar) reads that one cache — there is **no
  per-tab `/instances` polling**. If the stream errors (or `EventSource` is
  unavailable), the shell flips to a **5 s fallback poll** of `/instances`, and
  only then.
- **Per-tab data is pull-on-demand, not fast-polled.** Each tab fetches its own
  data when it mounts and relies on a **3–5 s `staleTime`** (global default
  4 s; the config schema uses 60 s since it rarely changes), so re-visiting a
  tab within that window serves cache instead of re-hitting the BFF. Only the
  *active* tab fetches.
- **Bounded refresh intervals.** The only periodic refetches are for genuinely
  live data, and none is faster than **1.5 s**: indexing **jobs** poll at 1.5 s
  *while a job is active* (and the Folders list at 2 s during that window) and
  then stop; the **Logs** tail polls at 3 s *only while auto-tail is on*; the
  Overview per-instance status refreshes at 8 s. Idle tabs issue zero periodic
  requests.

Net effect: with N projects open, the dashboard holds **one** SSE connection
for liveness regardless of N, and the active tab is the only thing fetching
detail — not N independent polling loops.

---

## Installation

The dashboard is **included with the CLI automatically on Python 3.12+** — there
is no extra to enable. The dependency carries a `python >= 3.12` marker, so on
Python 3.10/3.11 it's simply skipped and the CLI still installs:

```bash
pipx install brainpalace          # dashboard comes along on Python 3.12+
```

In a monorepo source checkout, `task install` installs the dashboard into the CLI
environment automatically. The `brainpalace dashboard` command imports the
dashboard package lazily and prints a friendly install hint on the older
interpreters where it isn't present.

### Auto-start with `brainpalace start`

On Python 3.12+, `brainpalace start` also ensures the dashboard is running and
prints its URL — opening a browser only when it actually launches one (never on
repeat starts, and never under `--json` or in a non-TTY/CI). It's best-effort: a
dashboard problem never fails `brainpalace start`. Opt out per-run with
`brainpalace start --no-dashboard`, or persistently by setting
`dashboard.autostart: false` (a toggle in the dashboard **Settings** tab, or the
`dashboard:` block of the XDG `config.yaml`).

---

## Related

- [README → Web Dashboard](../README.md#features)
- Plugin command: `brainpalace-plugin/commands/brainpalace-dashboard.md`
- [CONFIGURATION.md](CONFIGURATION.md) · [MCP_SETUP.md](MCP_SETUP.md)

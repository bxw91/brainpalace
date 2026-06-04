# Dashboard Plan 07 — `brainpalace dashboard` command + self-lifecycle + docs

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md). Depends on plans 01–06. **Setup-surface parity applies** (CLAUDE.md): a new CLI command must be reflected in plugin + MCP docs where relevant + CHANGELOG.

**Goal:** Add `brainpalace dashboard [start|stop|status]` that launches/stops the control-plane process (own port scan + pidfile), opens the browser, and is documented across surfaces.

**Architecture:** `dashboard.py` command spawns `uvicorn brainpalace_dashboard.app:create_app --factory` on `dashboard.port` (default 8787, scan to 8887), writes a dashboard pidfile/runtime under XDG state (`dashboard.json`), and opens `http://127.0.0.1:<port>/dashboard/`. Config read from XDG `config.yaml` `dashboard:` section. Optional `dashboard.token` adds a bearer-guard.

**Tech Stack:** Click, uvicorn, webbrowser, httpx.

---

## File Structure
- Create `brainpalace_dashboard/server.py` — `launch_dashboard()` / `stop_dashboard()` / `dashboard_status()` (port scan, pidfile, health).
- Create `brainpalace_dashboard/config.py` — read `dashboard:` config (port/host/poll_s/token/retention) from XDG.
- Create `brainpalace-cli/brainpalace_cli/commands/dashboard.py` — Click command group.
- Modify `brainpalace-cli/brainpalace_cli/cli.py` — register command.
- Modify `brainpalace_dashboard/app.py` — optional bearer-token middleware when `dashboard.token` set.
- Docs: `docs/DASHBOARD.md` (new, `last_validated`), README, CHANGELOG; plugin command stub; MCP note if applicable.

---

### Task 7.1: `dashboard.config` loader

**Files:** Create `brainpalace_dashboard/config.py`. Test: `tests/test_dashboard_config.py`.

- [ ] **Step 1: Failing test**

```python
# brainpalace-dashboard/tests/test_dashboard_config.py
def test_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from brainpalace_dashboard.config import load_dashboard_config
    cfg = load_dashboard_config()
    assert cfg.port == 8787 and cfg.host == "127.0.0.1" and cfg.poll_s == 5
    assert cfg.token is None

def test_reads_yaml(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    d = tmp_path / "brainpalace"; d.mkdir(parents=True)
    (d / "config.yaml").write_text("dashboard:\n  port: 9000\n  token: s3cret\n")
    from brainpalace_dashboard.config import load_dashboard_config
    cfg = load_dashboard_config()
    assert cfg.port == 9000 and cfg.token == "s3cret"
```

- [ ] **Step 2: Implement**

```python
# brainpalace-dashboard/brainpalace_dashboard/config.py
from __future__ import annotations
from dataclasses import dataclass
import yaml
from brainpalace_cli.xdg_paths import get_xdg_config_dir

@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    poll_s: int = 5
    token: str | None = None

def load_dashboard_config() -> DashboardConfig:
    cfg = DashboardConfig()
    path = get_xdg_config_dir() / "config.yaml"
    if path.exists():
        data = (yaml.safe_load(path.read_text()) or {}).get("dashboard", {}) or {}
        cfg.host = data.get("host", cfg.host)
        cfg.port = int(data.get("port", cfg.port))
        cfg.poll_s = int(data.get("poll_s", cfg.poll_s))
        cfg.token = data.get("token", cfg.token)
    return cfg
```

- [ ] **Step 3: Run → PASS. Step 4: Commit** (`feat(dashboard): dashboard config loader`).

---

### Task 7.2: dashboard self-lifecycle (`server.py`)

**Files:** Create `brainpalace_dashboard/server.py`. Test: `tests/test_dashboard_server.py`.

- [ ] **Step 1: Failing test**

```python
# brainpalace-dashboard/tests/test_dashboard_server.py
import brainpalace_dashboard.server as srv

def test_launch_writes_runtime_and_returns_url(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    class FakeProc: pid = 555
    monkeypatch.setattr(srv.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(srv, "_port_free", lambda host, port: True)
    monkeypatch.setattr(srv, "_wait_healthy", lambda url, timeout=20: True)
    url = srv.launch_dashboard(open_browser=False)
    assert url == "http://127.0.0.1:8787/dashboard/"
    rt = srv.read_dashboard_runtime()
    assert rt["pid"] == 555 and rt["port"] == 8787

def test_stop_signals_pid(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    srv.write_dashboard_runtime({"pid": 999, "port": 8787, "base_url": "http://127.0.0.1:8787/dashboard/"})
    killed = {}
    monkeypatch.setattr(srv.os, "kill", lambda pid, sig: killed.update(pid=pid))
    monkeypatch.setattr(srv, "_is_alive", lambda pid: False)
    out = srv.stop_dashboard()
    assert killed["pid"] == 999 and out["status"] == "stopped"
```

- [ ] **Step 2: Implement** `server.py` with: `_dashboard_runtime_path()` = `get_xdg_state_dir()/"dashboard.json"`, read/write/delete runtime, `_port_free`, `find_free_port(host, 8787, 8887)`, `_is_alive`, `_wait_healthy(url)` (GET `/dashboard/api/health`), `launch_dashboard(host?, port?, open_browser=True)` → scan port, `subprocess.Popen(["uvicorn", "brainpalace_dashboard.app:create_app", "--factory", "--host", host, "--port", str(port)])`, write runtime, wait healthy, `webbrowser.open(url)` if `open_browser`, return url. `stop_dashboard()` → SIGTERM pid, wait, delete runtime. `dashboard_status()` → runtime + health bool.
- [ ] **Step 3: Run → PASS. Step 4: Commit** (`feat(dashboard): self-lifecycle launcher/stopper`).

---

### Task 7.3: `brainpalace dashboard` Click command

**Files:** Create `brainpalace-cli/brainpalace_cli/commands/dashboard.py`. Modify `cli.py`. Test: `brainpalace-cli/tests/test_dashboard_command.py`.

- [ ] **Step 1: Failing test**

```python
# brainpalace-cli/tests/test_dashboard_command.py
from click.testing import CliRunner
from brainpalace_cli.cli import cli

def test_dashboard_start_invokes_launch(monkeypatch):
    import brainpalace_dashboard.server as srv
    monkeypatch.setattr(srv, "launch_dashboard", lambda **k: "http://127.0.0.1:8787/dashboard/")
    res = CliRunner().invoke(cli, ["dashboard", "start", "--no-open"])
    assert res.exit_code == 0
    assert "8787" in res.output

def test_dashboard_stop(monkeypatch):
    import brainpalace_dashboard.server as srv
    monkeypatch.setattr(srv, "stop_dashboard", lambda: {"status": "stopped"})
    res = CliRunner().invoke(cli, ["dashboard", "stop"])
    assert res.exit_code == 0
    assert "stopped" in res.output.lower()
```

- [ ] **Step 2: Implement** the command group with subcommands `start` (`--port`, `--host`, `--foreground`, `--no-open`), `stop`, `status`. `start` imports `brainpalace_dashboard.server` lazily (so the cli still works if the dashboard package isn't installed — print an install hint on ImportError). Register in `cli.py`: `cli.add_command(dashboard_command, name="dashboard")` and add it to the help "Project Commands" block.
- [ ] **Step 3: Run → PASS** (`cd brainpalace-cli && poetry run pytest tests/test_dashboard_command.py -v`). **Step 4: Commit** (`feat(cli): brainpalace dashboard command`).

---

### Task 7.4: Optional bearer-token guard

**Files:** Modify `brainpalace_dashboard/app.py`. Test: `tests/test_dashboard_auth.py`.

- [ ] **Step 1: Failing test** — with `BRAINPALACE_DASHBOARD_TOKEN=abc`, `GET /dashboard/api/instances` without header → 401; with `Authorization: Bearer abc` → 200. Without the env set → no auth required.
- [ ] **Step 2: Implement** a middleware in `create_app` that, when a token is configured (env `BRAINPALACE_DASHBOARD_TOKEN` or `load_dashboard_config().token`), requires `Authorization: Bearer <token>` on `/dashboard/api/**` (allow `/dashboard/api/health` and static unguarded). The SPA reads the token from a meta tag injected at serve time or a `?token=` once-exchange; for v1 simplest: same-origin localhost, token optional, document that enabling it is for shared machines.
- [ ] **Step 3: Run → PASS. Step 4: Commit** (`feat(dashboard): optional bearer-token guard`).

---

### Task 7.5: Bundle dashboard from the CLI at runtime

**Files:** Modify whatever mechanism bundles `brainpalace-server` into the CLI (find it: `grep -rn "brainpalace_server" brainpalace-cli/brainpalace_cli | grep -i bundle`). Mirror it for `brainpalace_dashboard`.

- [ ] **Step 1:** Read the existing server-bundling approach (path dep / vendored / entrypoint). 
- [ ] **Step 2:** Add `brainpalace-dashboard` as a dependency of `brainpalace-cli` `pyproject.toml` the same way the server is wired, so `pipx install brainpalace` ships the dashboard.
- [ ] **Step 3:** `task install` then `brainpalace dashboard status` works from a clean env.
- [ ] **Step 4: Commit** (`build(cli): bundle dashboard package`).

---

### Task 7.6: Docs across surfaces (parity)

- [ ] Create `docs/DASHBOARD.md`: overview, `brainpalace dashboard` usage, port model (8787 + project servers dynamic), every tab, config (`dashboard:` + `query_log:`), security note (localhost + optional token). Add `last_validated: 2026-06-04` front-matter.
- [ ] README: add a "Web Dashboard" feature bullet + one screenshot placeholder + the launch command.
- [ ] `docs/CHANGELOG.md`: feature entry.
- [ ] Plugin: add a minimal `brainpalace-plugin/commands/brainpalace-dashboard.md` command doc (mirrors CLI), per setup-surface parity.
- [ ] MCP: if the dashboard is reachable via MCP context, note it in `docs/MCP_SETUP.md`; otherwise add one line stating the dashboard is CLI-launched, not an MCP surface.
- [ ] Run `task lint:doc-freshness` (part of before-push) to confirm dates are consistent.
- [ ] **Commit** (`docs(dashboard): user guide + surface parity`).

---

## Plan 07 self-check
- [ ] `brainpalace dashboard start` launches control plane, opens browser; `stop`/`status` work; survives port 8787 already in use (scans up).
- [ ] Token guard works when configured, absent otherwise.
- [ ] `brainpalace --help` lists `dashboard`; docs updated on all relevant surfaces; `task check` green.

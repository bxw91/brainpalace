# Dashboard Plan 01 — Scaffold + InstanceService + Lifecycle API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`. Read [the index](2026-06-04-server-dashboard-00-index.md) "Shared conventions" first.

**Goal:** Create the `brainpalace-dashboard` subpackage and ship an InstanceService + REST API that lists every known project and can start/stop/restart each one.

**Architecture:** New Poetry package depending on `brainpalace-cli`. `InstanceService` reuses CLI lifecycle callables; FastAPI routes expose them. No SPA yet.

**Tech Stack:** FastAPI, uvicorn, httpx, pytest, Poetry.

---

## File Structure

- Create `brainpalace-dashboard/pyproject.toml` — Poetry package, dep on `brainpalace-cli` (path), fastapi, uvicorn, httpx, sse-starlette.
- Create `brainpalace-dashboard/brainpalace_dashboard/__init__.py` — `__version__`.
- Create `brainpalace_dashboard/app.py` — FastAPI factory, mounts routers, `/dashboard/api/health`.
- Create `brainpalace_dashboard/services/instances.py` — `InstanceService`.
- Create `brainpalace_dashboard/api/routes_instances.py` — lifecycle routes.
- Create `brainpalace_dashboard/api/__init__.py`, `services/__init__.py`.
- Modify `brainpalace-cli/brainpalace_cli/commands/start.py` — extract `launch_server(...)` callable (Task 1.0).
- Tests under `brainpalace-dashboard/tests/`.

---

### Task 1.0: Extract a non-Click `launch_server` callable in the CLI

**Files:**
- Modify: `brainpalace-cli/brainpalace_cli/commands/start.py`
- Test: `brainpalace-cli/tests/test_launch_server.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-cli/tests/test_launch_server.py
from pathlib import Path
import brainpalace_cli.commands.start as start_mod


def test_launch_server_is_callable_and_returns_runtime(tmp_path, monkeypatch):
    """launch_server spawns uvicorn and returns a runtime dict without Click."""
    calls = {}

    class FakeProc:
        pid = 4321

    def fake_popen(cmd, **kwargs):
        calls["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(start_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "update_registry", lambda *a, **k: None)

    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.yaml").write_text("server:\n  host: 127.0.0.1\n  port: 8123\n  auto_port: false\n")

    runtime = start_mod.launch_server(
        project_root=tmp_path, state_dir=state_dir, host=None, port=None, timeout=5
    )

    assert runtime["pid"] == 4321
    assert runtime["base_url"] == "http://127.0.0.1:8123"
    assert "uvicorn" in calls["cmd"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd brainpalace-cli && poetry run pytest tests/test_launch_server.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'launch_server'`.

- [ ] **Step 3: Refactor — pull the spawn logic out of `start_command` into `launch_server`**

In `start.py`, add a module-level function that contains the existing port-resolution + `subprocess.Popen([... "uvicorn" ...])` + `write_runtime` + `update_registry` block (currently inline in `start_command` around lines 277–347). Signature:

```python
def launch_server(
    project_root: Path,
    state_dir: Path,
    host: str | None = None,
    port: int | None = None,
    timeout: int = 120,
    strict: bool = False,
) -> dict[str, Any]:
    """Resolve bind host/port, spawn the uvicorn server, persist runtime.json,
    update the global registry, and return the runtime dict.

    Pure callable — no Click, no console printing. Raises RuntimeError on
    port-exhaustion or if the server fails its health check within ``timeout``.
    """
    config = read_config(state_dir)
    bind_host = host or config.get("host", "127.0.0.1")
    requested = port or config.get("port", 8000)
    if config.get("auto_port", True):
        bind_port = find_available_port(bind_host, requested, requested + 100)
        if bind_port is None:
            raise RuntimeError(f"No free port in {requested}-{requested + 100}")
    else:
        bind_port = requested
    base_url = f"http://{bind_host}:{bind_port}"

    cmd = [
        "uvicorn", "brainpalace_server.api.main:app",
        "--host", bind_host, "--port", str(bind_port),
    ]
    env = os.environ.copy()
    env["BRAINPALACE_STATE_DIR"] = str(state_dir)
    env["BRAINPALACE_PROJECT_ROOT"] = str(project_root)
    if strict:
        env["BRAINPALACE_STRICT"] = "true"
    process = subprocess.Popen(cmd, env=env)  # noqa: S603

    runtime = {
        "mode": "project",
        "pid": process.pid,
        "base_url": base_url,
        "host": bind_host,
        "port": bind_port,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_runtime(state_dir, runtime)
    update_registry(project_root, state_dir)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_health(base_url):
            return runtime
        time.sleep(0.5)
    raise RuntimeError(f"Server did not become healthy within {timeout}s at {base_url}")
```

Then change `start_command` to call `launch_server(...)` for the spawn path (keep its Click output/JSON formatting). Add `import time` if absent. Confirm `BRAINPALACE_STATE_DIR` / `BRAINPALACE_PROJECT_ROOT` env names match what the server reads — grep `brainpalace-server` for the env var the server uses for state dir; if it differs, use the server's actual name (do not invent).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd brainpalace-cli && poetry run pytest tests/test_launch_server.py -v`
Expected: PASS.

- [ ] **Step 5: Run the existing start tests to confirm no regression**

Run: `cd brainpalace-cli && poetry run pytest tests/ -k "start or runtime or multi_instance" -q`
Expected: PASS (all previously-passing tests still pass).

- [ ] **Step 6: Commit**

```bash
git add brainpalace-cli/brainpalace_cli/commands/start.py brainpalace-cli/tests/test_launch_server.py
git commit -m "refactor(cli): extract launch_server() callable from start_command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.1: Scaffold the `brainpalace-dashboard` Poetry package

**Files:**
- Create: `brainpalace-dashboard/pyproject.toml`
- Create: `brainpalace-dashboard/brainpalace_dashboard/__init__.py`
- Create: `brainpalace-dashboard/README.md`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[tool.poetry]
name = "brainpalace-dashboard"
version = "26.6.15"   # MUST equal brainpalace-server / brainpalace-cli version
description = "BrainPalace control-plane web dashboard"
authors = ["BrainPalace"]
packages = [{ include = "brainpalace_dashboard" }]

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.115"
uvicorn = "^0.30"
httpx = "^0.27"
sse-starlette = "^2.1"
brainpalace-cli = { path = "../brainpalace-cli", develop = true }

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.23"

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

> Pin the `version` to the current repo version. Find it: `grep '^version' brainpalace-server/pyproject.toml`. Use that exact value, not the literal above if it differs.

- [ ] **Step 2: Write `__init__.py`**

```python
# brainpalace-dashboard/brainpalace_dashboard/__init__.py
"""BrainPalace control-plane dashboard."""

__version__ = "26.6.15"  # keep equal to brainpalace-server __version__
```

- [ ] **Step 3: Write a one-line README**

```markdown
# brainpalace-dashboard
Control-plane web dashboard for managing all BrainPalace project servers. See docs/DASHBOARD.md.
```

- [ ] **Step 4: Install the package**

Run:
```bash
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
cd brainpalace-dashboard && poetry install
```
Expected: installs without error; `brainpalace-cli` resolves as a path dependency.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/pyproject.toml brainpalace-dashboard/brainpalace_dashboard/__init__.py brainpalace-dashboard/README.md
git commit -m "feat(dashboard): scaffold brainpalace-dashboard package

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.2: FastAPI app factory with health route

**Files:**
- Create: `brainpalace-dashboard/brainpalace_dashboard/app.py`
- Create: `brainpalace-dashboard/brainpalace_dashboard/api/__init__.py` (empty)
- Create: `brainpalace-dashboard/brainpalace_dashboard/services/__init__.py` (empty)
- Test: `brainpalace-dashboard/tests/test_app_health.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_app_health.py
from fastapi.testclient import TestClient
from brainpalace_dashboard.app import create_app


def test_health_route_returns_ok():
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_app_health.py -v`
Expected: FAIL — `ModuleNotFoundError: brainpalace_dashboard.app`.

- [ ] **Step 3: Implement `app.py`**

```python
# brainpalace-dashboard/brainpalace_dashboard/app.py
"""FastAPI application factory for the control-plane dashboard."""

from __future__ import annotations

from fastapi import FastAPI

from brainpalace_dashboard import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="BrainPalace Dashboard", version=__version__)

    @app.get("/dashboard/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
```

Create the two empty `__init__.py` files.

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_app_health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/app.py brainpalace-dashboard/brainpalace_dashboard/api/__init__.py brainpalace-dashboard/brainpalace_dashboard/services/__init__.py brainpalace-dashboard/tests/test_app_health.py
git commit -m "feat(dashboard): FastAPI app factory with health route

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.3: `InstanceService.list()` — deterministic id + merged status

**Files:**
- Create: `brainpalace-dashboard/brainpalace_dashboard/services/instances.py`
- Test: `brainpalace-dashboard/tests/test_instances_list.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_instances_list.py
from brainpalace_dashboard.services.instances import InstanceService, instance_id


def test_instance_id_is_deterministic_and_urlsafe():
    a = instance_id("/home/user/projects/foo")
    b = instance_id("/home/user/projects/foo")
    assert a == b
    assert a.isalnum() or "-" in a or "_" in a
    assert instance_id("/home/user/projects/bar") != a


def test_list_merges_running_scan_and_remembers(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))   # isolate known-store
    fake = [
        {
            "project_root": "/p/foo", "project_name": "foo", "state_dir": "/p/foo/.brainpalace",
            "base_url": "http://127.0.0.1:8001", "pid": 11,
            "mode": "project", "status": "running", "started_at": "2026-06-04T00:00:00Z",
        }
    ]
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances", lambda: fake
    )
    svc = InstanceService()
    rows = svc.list()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == instance_id("/p/foo")
    assert row["name"] == "foo"
    assert row["status"] == "running"
    assert row["base_url"] == "http://127.0.0.1:8001"


def test_stopped_instance_persists_after_it_leaves_the_registry(monkeypatch, tmp_path):
    """A project the dashboard has seen stays listed (status=stopped) even when
    it is no longer in the running registry — so it remains Start-able."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    root = "/p/foo"
    # First pass: it is running -> gets remembered.
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances",
        lambda: [{"project_root": root, "project_name": "foo",
                  "state_dir": root + "/.brainpalace", "base_url": "http://127.0.0.1:8001",
                  "pid": 11, "mode": "project", "status": "running", "started_at": ""}],
    )
    svc = InstanceService()
    svc.list()
    # Second pass: registry is now empty (server stopped & deregistered).
    monkeypatch.setattr(
        "brainpalace_dashboard.services.instances.scan_instances", lambda: []
    )
    rows = svc.list()
    assert len(rows) == 1
    assert rows[0]["id"] == instance_id(root)
    assert rows[0]["status"] == "stopped"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_instances_list.py -v`
Expected: FAIL — module/attr missing.

- [ ] **Step 3: Implement `instances.py` (list portion)**

```python
# brainpalace-dashboard/brainpalace_dashboard/services/instances.py
"""InstanceService: fleet listing + lifecycle (start/stop/restart).

The running registry (`registry.json`) only contains *currently running*
servers — `stop` deregisters a project. To keep stopped projects listed and
Start-able, the dashboard maintains its own durable store of every project it
has ever seen: `<XDG_STATE>/brainpalace/dashboard_known.json`.

list() = union(running scan, known store), reconciled to a status per row.
Stopping an instance leaves it in the known store (only the running registry
is pruned), so it persists as status="stopped".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from brainpalace_cli.commands.list_cmd import scan_instances, get_registry
from brainpalace_cli.commands.start import (
    launch_server,
    read_runtime,
    is_process_alive,
    check_health,
)
from brainpalace_cli.commands.stop import wait_for_process_exit, remove_from_registry
from brainpalace_cli.xdg_paths import get_xdg_state_dir


def instance_id(project_root: str) -> str:
    """Stable URL-safe id derived from the project root path."""
    digest = hashlib.sha1(project_root.encode("utf-8")).hexdigest()
    return digest[:16]


def _known_path() -> Path:
    return get_xdg_state_dir() / "dashboard_known.json"


def _load_known() -> dict[str, dict[str, Any]]:
    path = _known_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_known(known: dict[str, dict[str, Any]]) -> None:
    path = _known_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=2))


class InstanceNotFound(Exception):
    """Raised when no known project maps to an id."""


class InstanceService:
    """Fleet operations over the running registry + the durable known store."""

    def _remember(self, root: str, state_dir: str, name: str) -> None:
        known = _load_known()
        if root not in known or known[root].get("state_dir") != state_dir:
            known[root] = {"state_dir": state_dir, "project_name": name}
            _save_known(known)

    def forget(self, id_: str) -> dict[str, Any]:
        """Remove a project from the dashboard's list ('Remove from list' action).
        Does NOT touch the project on disk or its config."""
        known = _load_known()
        for root in list(known):
            if instance_id(root) == id_:
                del known[root]
                _save_known(known)
                return {"id": id_, "forgotten": True}
        return {"id": id_, "forgotten": False}

    def register(self, project_root: str) -> dict[str, Any]:
        """Add an existing project dir to the dashboard's list."""
        root = str(Path(project_root).resolve())
        state_dir = str(Path(root) / ".brainpalace")
        self._remember(root, state_dir, Path(root).name)
        return {"id": instance_id(root), "project_root": root}

    def list(self) -> list[dict[str, Any]]:
        # 1) Running servers from the live scan; remember each.
        running: dict[str, dict[str, Any]] = {}
        for inst in scan_instances():
            root = inst["project_root"]
            state_dir = inst.get("state_dir", str(Path(root) / ".brainpalace"))
            name = inst.get("project_name") or Path(root).name
            self._remember(root, state_dir, name)
            running[root] = {
                "id": instance_id(root),
                "name": name,
                "project_root": root,
                "state_dir": state_dir,
                "base_url": inst.get("base_url", ""),
                "pid": inst.get("pid", 0),
                "mode": inst.get("mode", "project"),
                "status": inst.get("status", "stale"),
                "started_at": inst.get("started_at", ""),
            }
        # 2) Known-but-not-running projects -> status "stopped".
        rows = list(running.values())
        for root, entry in _load_known().items():
            if root in running:
                continue
            rows.append({
                "id": instance_id(root),
                "name": entry.get("project_name") or Path(root).name,
                "project_root": root,
                "state_dir": entry.get("state_dir", str(Path(root) / ".brainpalace")),
                "base_url": "",
                "pid": 0,
                "mode": "project",
                "status": "stopped",
                "started_at": "",
            })
        rows.sort(key=lambda r: r["name"].lower())
        return rows

    def _resolve(self, id_: str) -> dict[str, Any]:
        """Map an id back to a project (running registry first, then known store)."""
        registry = get_registry()
        for root, entry in registry.items():
            if instance_id(root) == id_:
                return {"project_root": root, **entry}
        for root, entry in _load_known().items():
            if instance_id(root) == id_:
                return {"project_root": root, **entry}
        raise InstanceNotFound(id_)
```

> Confirm `get_registry()` / `scan_instances()` entry keys (`state_dir`, `project_name`) by reading `list_cmd.py`; adjust if they differ. `scan_instances()` may not include `state_dir` — if absent, fall back to `<root>/.brainpalace` as shown.

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_instances_list.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/services/instances.py brainpalace-dashboard/tests/test_instances_list.py
git commit -m "feat(dashboard): InstanceService.list with durable known-projects store

Stopped instances persist (status=stopped) via dashboard_known.json so they
stay Start-able even after stop deregisters them from registry.json.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.4: `InstanceService.start/stop/restart`

**Files:**
- Modify: `brainpalace-dashboard/brainpalace_dashboard/services/instances.py`
- Test: `brainpalace-dashboard/tests/test_instances_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_instances_lifecycle.py
from pathlib import Path
import brainpalace_dashboard.services.instances as inst_mod
from brainpalace_dashboard.services.instances import InstanceService, instance_id


def _patch_registry(monkeypatch, root, state_dir):
    monkeypatch.setattr(
        inst_mod, "get_registry",
        lambda: {root: {"state_dir": str(state_dir), "project_name": "foo"}},
    )


def test_start_invokes_launch_server(monkeypatch, tmp_path):
    root = str(tmp_path)
    state = tmp_path / ".brainpalace"
    state.mkdir()
    _patch_registry(monkeypatch, root, state)
    seen = {}
    monkeypatch.setattr(
        inst_mod, "launch_server",
        lambda **kw: seen.update(kw) or {"pid": 99, "base_url": "http://127.0.0.1:8005"},
    )
    svc = InstanceService()
    out = svc.start(instance_id(root))
    assert out["pid"] == 99
    assert seen["project_root"] == Path(root)


def test_stop_signals_pid_and_deregisters(monkeypatch, tmp_path):
    root = str(tmp_path)
    state = tmp_path / ".brainpalace"
    state.mkdir()
    _patch_registry(monkeypatch, root, state)
    monkeypatch.setattr(inst_mod, "read_runtime", lambda sd: {"pid": 1234})
    killed = {}
    monkeypatch.setattr(inst_mod.os, "kill", lambda pid, sig: killed.update(pid=pid, sig=sig))
    monkeypatch.setattr(inst_mod, "wait_for_process_exit", lambda pid, timeout=10.0: True)
    monkeypatch.setattr(inst_mod, "remove_from_registry", lambda root: killed.update(dereg=True))
    monkeypatch.setattr(inst_mod, "delete_runtime", lambda sd: None)
    svc = InstanceService()
    out = svc.stop(instance_id(root))
    assert killed["pid"] == 1234
    assert killed["dereg"] is True
    assert out["status"] == "stopped"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_instances_lifecycle.py -v`
Expected: FAIL — `start`/`stop` not defined.

- [ ] **Step 3: Implement start/stop/restart**

Add imports `import os, signal, time` at the top of `instances.py` and `from brainpalace_cli.commands.start import delete_runtime`. Add methods to `InstanceService`:

```python
    def start(self, id_: str, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        entry = self._resolve(id_)
        root = Path(entry["project_root"])
        state_dir = Path(entry["state_dir"]) if entry.get("state_dir") else root / ".brainpalace"
        return launch_server(
            project_root=root, state_dir=state_dir, host=host, port=port
        )

    def stop(self, id_: str, force: bool = False) -> dict[str, Any]:
        entry = self._resolve(id_)
        root = Path(entry["project_root"])
        state_dir = Path(entry["state_dir"]) if entry.get("state_dir") else root / ".brainpalace"
        runtime = read_runtime(state_dir) or {}
        pid = runtime.get("pid", 0)
        if pid and is_process_alive(pid):
            os.kill(pid, signal.SIGTERM)
            if not wait_for_process_exit(pid, timeout=10.0):
                if force:
                    os.kill(pid, signal.SIGKILL)
                    wait_for_process_exit(pid, timeout=5.0)
                else:
                    return {"id": id_, "status": "unhealthy",
                            "detail": "SIGTERM timed out; retry with force"}
        delete_runtime(state_dir)
        remove_from_registry(root)
        return {"id": id_, "status": "stopped"}

    def restart(self, id_: str, host: str | None = None, port: int | None = None) -> dict[str, Any]:
        self.stop(id_)
        time.sleep(0.3)
        return self.start(id_, host=host, port=port)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_instances_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/services/instances.py brainpalace-dashboard/tests/test_instances_lifecycle.py
git commit -m "feat(dashboard): InstanceService start/stop/restart

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.5: Instance lifecycle REST routes

**Files:**
- Create: `brainpalace-dashboard/brainpalace_dashboard/api/routes_instances.py`
- Modify: `brainpalace-dashboard/brainpalace_dashboard/app.py`
- Test: `brainpalace-dashboard/tests/test_routes_instances.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_routes_instances.py
from fastapi.testclient import TestClient
import brainpalace_dashboard.api.routes_instances as routes
from brainpalace_dashboard.app import create_app


def test_list_endpoint(monkeypatch):
    monkeypatch.setattr(
        routes.service, "list",
        lambda: [{"id": "abc", "name": "foo", "status": "running",
                  "base_url": "http://127.0.0.1:8001", "project_root": "/p/foo",
                  "pid": 1, "mode": "project", "started_at": ""}],
    )
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "abc"


def test_start_endpoint(monkeypatch):
    monkeypatch.setattr(routes.service, "start", lambda id_: {"pid": 7, "base_url": "http://x"})
    client = TestClient(create_app())
    resp = client.post("/dashboard/api/instances/abc/start")
    assert resp.status_code == 200
    assert resp.json()["pid"] == 7


def test_stop_endpoint(monkeypatch):
    monkeypatch.setattr(routes.service, "stop", lambda id_, force=False: {"id": id_, "status": "stopped"})
    client = TestClient(create_app())
    resp = client.post("/dashboard/api/instances/abc/stop")
    assert resp.json()["status"] == "stopped"


def test_register_and_forget_endpoints(monkeypatch):
    monkeypatch.setattr(routes.service, "register", lambda path: {"id": "new", "project_root": path})
    monkeypatch.setattr(routes.service, "forget", lambda id_: {"id": id_, "forgotten": True})
    client = TestClient(create_app())
    r1 = client.post("/dashboard/api/instances/register", json={"path": "/p/bar"})
    assert r1.json()["id"] == "new"
    r2 = client.delete("/dashboard/api/instances/abc")
    assert r2.json()["forgotten"] is True
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_routes_instances.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement routes + wire into app**

```python
# brainpalace-dashboard/brainpalace_dashboard/api/routes_instances.py
"""Instance lifecycle endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from brainpalace_dashboard.services.instances import InstanceService, InstanceNotFound

router = APIRouter(prefix="/dashboard/api/instances", tags=["instances"])
service = InstanceService()


@router.get("")
def list_instances() -> list[dict]:
    return service.list()


@router.get("/{id_}")
def get_instance(id_: str) -> dict:
    for row in service.list():
        if row["id"] == id_:
            return row
    raise HTTPException(status_code=404, detail="instance not found")


@router.post("/{id_}/start")
def start_instance(id_: str) -> dict:
    try:
        return service.start(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{id_}/stop")
def stop_instance(id_: str, force: bool = Query(False)) -> dict:
    try:
        return service.stop(id_, force=force)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found")


@router.post("/{id_}/restart")
def restart_instance(id_: str) -> dict:
    try:
        return service.restart(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found")
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


class RegisterBody(BaseModel):
    path: str


@router.post("/register")
def register_instance(body: RegisterBody) -> dict:
    return service.register(body.path)


@router.delete("/{id_}")
def forget_instance(id_: str) -> dict:
    """Remove a project from the dashboard list. Does not delete anything on disk."""
    return service.forget(id_)
```

> Add `from pydantic import BaseModel` to the imports. Route order: declare `/register` **before** `/{id_}` is matched on GET — FastAPI matches by registration order within a method, and these are POST/DELETE vs the GET `/{id_}`, so there's no clash, but keep `/register` (POST) above any future `POST /{id_}` to avoid capture.

In `app.py`, import and include the router:

```python
from brainpalace_dashboard.api import routes_instances

# inside create_app(), after defining health:
    app.include_router(routes_instances.router)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_routes_instances.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/api/routes_instances.py brainpalace-dashboard/brainpalace_dashboard/app.py brainpalace-dashboard/tests/test_routes_instances.py
git commit -m "feat(dashboard): instance lifecycle REST routes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.6: Integration test — real ephemeral server lifecycle

**Files:**
- Test: `brainpalace-dashboard/tests/test_integration_lifecycle.py`

- [ ] **Step 1: Write the integration test (marked slow)**

```python
# brainpalace-dashboard/tests/test_integration_lifecycle.py
import time
import pytest
import httpx

pytestmark = pytest.mark.integration


def test_start_then_stop_real_server(tmp_path, monkeypatch):
    """Init a throwaway project, start via service, hit health, stop."""
    from brainpalace_dashboard.services.instances import InstanceService, instance_id
    import brainpalace_dashboard.services.instances as inst_mod

    root = tmp_path
    state = root / ".brainpalace"
    state.mkdir()
    # Minimal config: chroma backend, auto_port on, no providers needed for /health/.
    (state / "config.yaml").write_text(
        "server:\n  host: 127.0.0.1\n  port: 8600\n  auto_port: true\n"
        "storage:\n  backend: chroma\n"
    )
    monkeypatch.setattr(
        inst_mod, "get_registry",
        lambda: {str(root): {"state_dir": str(state), "project_name": "itest"}},
    )

    svc = InstanceService()
    rt = svc.start(instance_id(str(root)))
    try:
        base = rt["base_url"]
        r = httpx.get(f"{base}/health/", timeout=5)
        assert r.status_code == 200
    finally:
        out = svc.stop(instance_id(str(root)))
        assert out["status"] == "stopped"
```

- [ ] **Step 2: Run it**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_integration_lifecycle.py -v -m integration`
Expected: PASS. If `/health/` needs more config, add the minimum from the server's `config.yaml` template (read `brainpalace init` defaults) — do not stub.

- [ ] **Step 3: Register the `integration` marker**

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:
```toml
markers = ["integration: spins up a real server (slow)"]
```

- [ ] **Step 4: Commit**

```bash
git add brainpalace-dashboard/tests/test_integration_lifecycle.py brainpalace-dashboard/pyproject.toml
git commit -m "test(dashboard): integration lifecycle against real server

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 1.7: Wire dashboard into Taskfile + version-consistency

**Files:**
- Modify: `Taskfile.yml`
- Modify: `brainpalace-cli/tests/test_version_consistency.py` (or wherever the version test lives)

- [ ] **Step 1: Find the version-consistency test**

Run: `grep -rln "version_consistency\|__version__" brainpalace-cli/tests brainpalace-server/tests | head`
Read it; it asserts server and cli versions match.

- [ ] **Step 2: Extend it to include the dashboard**

Add `brainpalace_dashboard.__version__` to the set of versions asserted equal. Show the exact added lines (mirror the existing pattern in that test file).

- [ ] **Step 3: Add Taskfile hooks**

In `Taskfile.yml`, mirror the existing `install:cli` / `test:cli` tasks with `install:dashboard` (`cd brainpalace-dashboard && poetry install`) and `test:dashboard` (`cd brainpalace-dashboard && poetry run pytest -q -m "not integration"`). Add them to the aggregate `install` and `test` task deps.

- [ ] **Step 4: Run the aggregate**

Run: `task test:dashboard` and `task install`
Expected: PASS / installs.

- [ ] **Step 5: Commit**

```bash
git add Taskfile.yml brainpalace-cli/tests/test_version_consistency.py
git commit -m "build(dashboard): wire into Taskfile + version-consistency

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Plan 01 self-check (run before moving to plan 02)
- [ ] `task test:dashboard` green; `task check` green.
- [ ] `GET /dashboard/api/instances` returns the fleet; start/stop/restart routes work against a real server (Task 1.6).
- [ ] No lifecycle logic was copy-pasted — `launch_server` is the single source.
- [ ] **Stopped instances persist:** start a real instance, list (it's `running`), stop it, list again — it still appears as `status: "stopped"` and Start works. The dashboard does not depend on the project server being up to list or manage it.
- [ ] `stop` leaves the project in `dashboard_known.json` (only prunes the running registry); `DELETE /instances/{id}` (forget) is the only thing that removes it from the list, and it touches nothing on disk.

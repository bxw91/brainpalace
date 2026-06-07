"""InstanceService: fleet listing + lifecycle (start/stop/restart).

The running registry (``registry.json``) only contains *currently running*
servers — ``stop`` deregisters a project. To keep stopped projects listed and
Start-able, the dashboard maintains its own durable store of every project it
has ever seen: ``<XDG_STATE>/brainpalace/dashboard_known.json``.

list() = union(running scan, known store), reconciled to a status per row.
Stopping an instance leaves it in the known store (only the running registry
is pruned), so it persists as status="stopped".

Reused CLI symbols (confirmed against brainpalace-cli source):
  - ``scan_instances`` / ``get_registry`` (list_cmd) — entry dicts carry
    ``project_root, project_name, base_url, pid, mode, status, started_at``.
    NOTE: ``scan_instances()`` rows do NOT include ``state_dir`` (the registry
    entries do), so we fall back to ``<root>/.brainpalace`` when absent.
  - ``launch_server`` (start) — single spawn source of truth.
  - ``get_xdg_state_dir`` (xdg_paths) — honors ``XDG_STATE_HOME``.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from brainpalace_cli.commands.list_cmd import get_registry, scan_instances
from brainpalace_cli.commands.start import (
    check_health,
    delete_runtime,
    is_process_alive,
    launch_server,
    read_runtime,
)
from brainpalace_cli.commands.stop import remove_from_registry, wait_for_process_exit
from brainpalace_cli.xdg_paths import get_xdg_state_dir

__all__ = [
    "InstanceService",
    "InstanceNotFound",
    "instance_id",
    "scan_instances",
    "get_registry",
    "launch_server",
    "read_runtime",
    "delete_runtime",
    "is_process_alive",
    "check_health",
    "wait_for_process_exit",
    "remove_from_registry",
]


def instance_id(project_root: str) -> str:
    """Stable URL-safe id derived from the project root path."""
    digest = hashlib.sha1(project_root.encode("utf-8")).hexdigest()
    return digest[:16]


def _known_path() -> Path:
    state_dir: Path = get_xdg_state_dir()
    return state_dir / "dashboard_known.json"


def _load_known() -> dict[str, dict[str, Any]]:
    path = _known_path()
    if not path.exists():
        return {}
    try:
        result: dict[str, dict[str, Any]] = json.loads(path.read_text())
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _save_known(known: dict[str, dict[str, Any]]) -> None:
    path = _known_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=2))


class InstanceNotFound(Exception):  # noqa: N818 - public API name used by routes
    """Raised when no known project maps to an id."""


def _reap_if_child(pid: int) -> None:
    """Reap ``pid`` if it is a child of this process.

    When the dashboard spawns a server in-process (via ``launch_server``'s
    ``Popen``) and later SIGTERMs it, the kernel keeps the exited child as a
    zombie until it is wait()ed for — and ``os.kill(pid, 0)`` reports a zombie
    as *alive*, so ``wait_for_process_exit`` would otherwise never observe it
    die. Reaping clears the zombie. ``ChildProcessError`` means it is not our
    child (e.g. a CLI-daemonized server reparented to init), which is fine — the
    OS reaps it elsewhere.
    """
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def _wait_for_exit_reaping(pid: int, timeout: float) -> bool:
    """Like ``wait_for_process_exit`` but reaps the child between polls so an
    in-process-spawned server's zombie is observed as exited."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _reap_if_child(pid)
        if not is_process_alive(pid):
            return True
        time.sleep(0.2)
    return False


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
            rows.append(
                {
                    "id": instance_id(root),
                    "name": entry.get("project_name") or Path(root).name,
                    "project_root": root,
                    "state_dir": entry.get(
                        "state_dir", str(Path(root) / ".brainpalace")
                    ),
                    "base_url": "",
                    "pid": 0,
                    "mode": "project",
                    "status": "stopped",
                    "started_at": "",
                }
            )
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

    def start(
        self, id_: str, host: str | None = None, port: int | None = None
    ) -> dict[str, Any]:
        entry = self._resolve(id_)
        root = Path(entry["project_root"])
        state_dir = (
            Path(entry["state_dir"])
            if entry.get("state_dir")
            else root / ".brainpalace"
        )
        runtime: dict[str, Any] = launch_server(
            project_root=root, state_dir=state_dir, host=host, port=port
        )
        return runtime

    def stop(self, id_: str, force: bool = False) -> dict[str, Any]:
        entry = self._resolve(id_)
        root = Path(entry["project_root"])
        state_dir = (
            Path(entry["state_dir"])
            if entry.get("state_dir")
            else root / ".brainpalace"
        )
        runtime = read_runtime(state_dir) or {}
        pid = runtime.get("pid", 0)
        if pid and is_process_alive(pid):
            os.kill(pid, signal.SIGTERM)
            # Reaping wait: when the dashboard spawned the server in-process, the
            # exited child is a zombie that os.kill(pid, 0) still reports alive
            # until reaped — _wait_for_exit_reaping clears it.
            if not _wait_for_exit_reaping(pid, timeout=10.0):
                if force:
                    os.kill(pid, signal.SIGKILL)
                    _wait_for_exit_reaping(pid, timeout=5.0)
                else:
                    return {
                        "id": id_,
                        "status": "unhealthy",
                        "detail": "SIGTERM timed out; retry with force",
                    }
        delete_runtime(state_dir)
        remove_from_registry(root)
        return {"id": id_, "status": "stopped"}

    def restart(
        self, id_: str, host: str | None = None, port: int | None = None
    ) -> dict[str, Any]:
        self.stop(id_)
        time.sleep(0.3)
        return self.start(id_, host=host, port=port)

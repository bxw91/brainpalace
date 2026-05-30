"""CWD-based BrainPalace server discovery.

Walks up from the current directory to find the project's ``.brainpalace/``
directory, reads ``runtime.json``, and returns the URL of the running server
that owns that project — so CLI commands work without an explicit ``--url``.
See plan B1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


def discover_project_dir(start: Path | None = None) -> Path | None:
    """Find the project directory by walking up from ``start``.

    Walks up from ``start`` (default: current working directory) looking for a
    ``.brainpalace/`` subdirectory and returns the first match. Never walks
    above ``$HOME`` and never escapes it.

    Args:
        start: Directory to start from. Defaults to the current directory.

    Returns:
        The project directory (the parent of ``.brainpalace/``), or ``None``
        if none is found at or below ``$HOME``.
    """
    start = (start or Path.cwd()).resolve()
    home = Path.home().resolve()

    # Refuse to search if start is outside $HOME.
    if start != home and home not in start.parents:
        return None

    current = start
    while True:
        if (current / ".brainpalace").is_dir():
            return current
        if current == home:
            return None
        parent = current.parent
        if parent == current:  # filesystem root
            return None
        current = parent


def discover_server_url(start: Path | None = None) -> str | None:
    """Find the URL of the running server for the project containing ``start``.

    Resolves the project directory (:func:`discover_project_dir`), reads
    ``.brainpalace/runtime.json``, and validates the server is alive:

    1. ``runtime.json`` exists, parses, and has ``base_url`` + a positive ``pid``.
    2. The recorded PID is alive.
    3. ``GET /health/`` returns 200.
    4. If the server exposes ``GET /runtime/`` (B8), its ``project_root`` must
       match the discovered project — guards against a recycled PID or a
       different project's server bound to the same port.

    Args:
        start: Directory to start from. Defaults to the current directory.

    Returns:
        The validated server URL, or ``None`` if there is no live owning server.
    """
    project = discover_project_dir(start)
    if project is None:
        return None

    runtime_file = project / ".brainpalace" / "runtime.json"
    try:
        data = json.loads(runtime_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    url = data.get("base_url")
    pid = data.get("pid")
    if not url or not isinstance(pid, int) or pid <= 0:
        return None

    # The recorded PID must be alive.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # Process exists but owned by another user — treat as alive.

    base = str(url).rstrip("/")

    # Health check.
    try:
        health = httpx.get(f"{base}/health/", timeout=2.0)
    except httpx.HTTPError:
        return None
    if health.status_code != 200:
        return None

    # Recycled-PID guard: confirm the server actually serves THIS project (B8).
    try:
        runtime_resp = httpx.get(f"{base}/runtime/", timeout=2.0)
    except httpx.HTTPError:
        return None
    if runtime_resp.status_code == 200:
        try:
            served = str(runtime_resp.json().get("project_root", ""))
        except (ValueError, KeyError):
            served = ""
        if served and Path(served).resolve() != project:
            return None

    return base

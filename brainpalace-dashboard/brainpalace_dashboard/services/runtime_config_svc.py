"""RuntimeConfigService: read/validate/write the per-project ``config.json``.

``config.json`` holds the runtime *bind* the project server uses at start —
``bind_host`` / ``port_range_start`` / ``port_range_end`` / ``auto_port`` (read
by ``brainpalace_cli.commands.start.read_config`` / ``resolve_bind_port``). The
YAML ``server.*`` / ``api.*`` sections are intentionally NOT the runtime source;
editing them is a no-op for the running server, so the bind is edited here.

Changes apply only on a server **restart** — the caller surfaces a
``restart_required`` flag and offers Save+Restart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# The four runtime-bind keys the dashboard surfaces. Other config.json keys
# (chunk_size, exclude_patterns, project_root, …) are preserved verbatim on
# write but not exposed as editable controls here.
BIND_HOST_DEFAULT = "127.0.0.1"
PORT_RANGE_START_DEFAULT = 8000
PORT_RANGE_END_DEFAULT = 8100
AUTO_PORT_DEFAULT = True

_BIND_KEYS = ("bind_host", "port_range_start", "port_range_end", "auto_port")


class RuntimeConfigError(Exception):
    """Raised when a runtime-config write fails validation (all-or-nothing)."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} runtime-config validation error(s)")


def _is_int(v: Any) -> bool:
    # bool is a subclass of int; reject it as a port value.
    return isinstance(v, int) and not isinstance(v, bool)


def validate_runtime_config(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the editable bind fields. Returns ``[{field, message}]``.

    Rules: ports are integers 1–65535, ``port_range_start <= port_range_end``,
    ``bind_host`` is a non-empty string, ``auto_port`` is a boolean. Only the
    fields present in ``values`` are checked.
    """
    errors: list[dict[str, Any]] = []

    if "bind_host" in values:
        host = values["bind_host"]
        if not isinstance(host, str) or not host.strip():
            errors.append(
                {"field": "bind_host", "message": "Host must be a non-empty string."}
            )

    for key in ("port_range_start", "port_range_end"):
        if key in values:
            port = values[key]
            if not _is_int(port) or not (1 <= port <= 65535):
                errors.append(
                    {"field": key, "message": "Port must be an integer 1–65535."}
                )

    start = values.get("port_range_start")
    end = values.get("port_range_end")
    if isinstance(start, int) and isinstance(end, int) and start > end:
        errors.append(
            {
                "field": "port_range_end",
                "message": "Port range end must be ≥ start.",
            }
        )

    if "auto_port" in values and not isinstance(values["auto_port"], bool):
        errors.append(
            {"field": "auto_port", "message": "Auto-port must be true or false."}
        )

    return errors


class RuntimeConfigService:
    def _config_path(self, state_dir: Path) -> Path:
        return Path(state_dir) / "config.json"

    @staticmethod
    def _raw(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def read(self, state_dir: Path) -> dict[str, Any]:
        """Return the four editable bind fields, falling back to CLI defaults."""
        raw = self._raw(self._config_path(Path(state_dir)))
        return {
            "bind_host": raw.get("bind_host", BIND_HOST_DEFAULT),
            "port_range_start": raw.get("port_range_start", PORT_RANGE_START_DEFAULT),
            "port_range_end": raw.get("port_range_end", PORT_RANGE_END_DEFAULT),
            "auto_port": raw.get("auto_port", AUTO_PORT_DEFAULT),
        }

    def write(self, state_dir: Path, values: dict[str, Any]) -> None:
        """Validate then atomically merge the bind fields into config.json.

        Only the four bind keys are written; any other keys already in the file
        (chunk_size, exclude_patterns, project_root, …) are preserved verbatim.
        """
        errors = validate_runtime_config(values)
        if errors:
            raise RuntimeConfigError(errors)
        path = self._config_path(Path(state_dir))
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._raw(path)
        merged = dict(existing)
        for key in _BIND_KEYS:
            if key in values:
                merged[key] = values[key]
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(merged, indent=2))
        if path.exists():
            path.replace(path.with_suffix(".json.bak"))
        os.replace(tmp, path)

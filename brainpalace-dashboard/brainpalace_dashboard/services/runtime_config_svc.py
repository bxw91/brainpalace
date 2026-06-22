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

from brainpalace_cli.xdg_paths import get_xdg_config_dir

# The four runtime-bind keys the dashboard surfaces. Other config.json keys
# (chunk_size, exclude_patterns, project_root, …) are preserved verbatim on
# write but not exposed as editable controls here.
BIND_HOST_DEFAULT = "127.0.0.1"
PORT_RANGE_START_DEFAULT = 8000
PORT_RANGE_END_DEFAULT = 8100
AUTO_PORT_DEFAULT = True

_BIND_KEYS = ("bind_host", "port_range_start", "port_range_end", "auto_port")

# Per-field metadata for the inherit-first control: code default + which process
# "type" consumes the field. The bind is read by the CLI when it starts the
# SERVER, so every current field is `server`-type; the structure supports
# `cli`-type runtime fields without code changes here.
RUNTIME_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "bind_host", "default": BIND_HOST_DEFAULT, "type": "server"},
    {"key": "port_range_start", "default": PORT_RANGE_START_DEFAULT, "type": "server"},
    {"key": "port_range_end", "default": PORT_RANGE_END_DEFAULT, "type": "server"},
    {"key": "auto_port", "default": AUTO_PORT_DEFAULT, "type": "server"},
)
_DEFAULTS = {f["key"]: f["default"] for f in RUNTIME_FIELDS}


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

    def _global_path(self) -> Path:
        """Machine-wide bind defaults — the XDG ``config.json`` (parallel to the
        global ``config.yaml``). The CLI reads it at server start (start.read_config).
        """
        return Path(get_xdg_config_dir()) / "config.json"

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
        """Effective bind: project ``config.json`` > global > code default."""
        project = self._raw(self._config_path(Path(state_dir)))
        global_ = self._raw(self._global_path())
        return {
            key: project.get(key, global_.get(key, _DEFAULTS[key]))
            for key in _BIND_KEYS
        }

    def read_global(self) -> dict[str, Any]:
        """The machine-wide bind defaults (bind keys only; code default fallback)."""
        raw = self._raw(self._global_path())
        return {key: raw.get(key, _DEFAULTS[key]) for key in _BIND_KEYS}

    def effective(self, state_dir: Path) -> dict[str, dict[str, Any]]:
        """Per-field effective value + provenance: project > global > code default.

        ``source`` is ``"file"`` (this project's ``config.json``), ``"global"``
        (machine-wide ``config.json``) or ``"default"`` (CLI built-in).
        ``inherited`` is the value+source the key falls back to when the project
        override is reverted (global, else code default). Powers the inherit-first
        Runtime bind section in the Config tab.
        """
        project = self._raw(self._config_path(Path(state_dir)))
        global_ = self._raw(self._global_path())
        out: dict[str, dict[str, Any]] = {}
        for key in _BIND_KEYS:
            inherited = self._global_or_default(key, global_)
            if key in project:
                out[key] = {
                    "value": project[key],
                    "source": "file",
                    "inherited": inherited,
                }
            elif key in global_:
                out[key] = {
                    "value": global_[key],
                    "source": "global",
                    "inherited": None,
                }
            else:
                out[key] = {
                    "value": _DEFAULTS[key],
                    "source": "default",
                    "inherited": None,
                }
        return out

    def effective_global(self) -> dict[str, dict[str, Any]]:
        """Per-field effective for the GLOBAL bind layer: global file > code default."""
        global_ = self._raw(self._global_path())
        out: dict[str, dict[str, Any]] = {}
        for key in _BIND_KEYS:
            if key in global_:
                out[key] = {
                    "value": global_[key],
                    "source": "global",
                    "inherited": {"value": _DEFAULTS[key], "source": "default"},
                }
            else:
                out[key] = {
                    "value": _DEFAULTS[key],
                    "source": "default",
                    "inherited": None,
                }
        return out

    @staticmethod
    def _global_or_default(key: str, global_: dict[str, Any]) -> dict[str, Any]:
        """What a project key reverts to when unset: the global value, else default."""
        if key in global_:
            return {"value": global_[key], "source": "global"}
        return {"value": _DEFAULTS[key], "source": "default"}

    def write(
        self,
        state_dir: Path,
        values: dict[str, Any],
        unset: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Validate then atomically merge the bind fields into the project config.json.

        Only the four bind keys are written; any other keys already in the file
        (chunk_size, exclude_patterns, project_root, …) are preserved verbatim.
        ``unset`` lists bind keys to REMOVE so they revert to global / code default —
        staged in the form and applied in the same Save.
        """
        self._write_to(self._config_path(Path(state_dir)), values, unset)

    def write_global(
        self,
        values: dict[str, Any],
        unset: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Atomically merge the bind fields into the machine-wide XDG config.json."""
        self._write_to(self._global_path(), values, unset)

    def _write_to(
        self,
        path: Path,
        values: dict[str, Any],
        unset: list[str] | tuple[str, ...] = (),
    ) -> None:
        errors = validate_runtime_config(values)
        if errors:
            raise RuntimeConfigError(errors)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._raw(path)
        merged = dict(existing)
        for key in _BIND_KEYS:
            if key in values:
                merged[key] = values[key]
        for key in unset:
            if key in _BIND_KEYS:
                merged.pop(key, None)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(merged, indent=2))
        if path.exists():
            path.replace(path.with_suffix(".json.bak"))
        os.replace(tmp, path)

"""Dashboard configuration loader.

Reads the dashboard's own config file
(``$XDG_CONFIG_HOME/brainpalace/dashboard.yaml``, default
``~/.config/brainpalace/dashboard.yaml``), separate from the per-instance server
``config.yaml``. A legacy ``config.yaml`` ``dashboard:`` block is auto-migrated
into ``dashboard.yaml`` on first load. All keys are optional; unset keys fall
back to the dataclass defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from brainpalace_cli.xdg_paths import get_xdg_config_dir

#: Returned/accepted in place of a real token so it is never exposed to the SPA.
TOKEN_MASK = "********"

#: Allowed values for the display-format preferences (validated on write).
TIME_FORMATS = ("24h", "12h")
DATE_FORMATS = ("dd.mm.yyyy", "mm.dd.yyyy", "yyyy-mm-dd")


class DashboardConfigError(Exception):
    """Raised when a control-plane settings write fails validation."""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__(f"{len(errors)} dashboard settings error(s)")


@dataclass
class DashboardConfig:
    """Resolved dashboard settings.

    Attributes:
        host: Bind host for the dashboard process.
        port: Preferred port (scanned upward if busy).
        poll_s: SPA polling interval hint (seconds).
        token: Optional bearer token guarding ``/dashboard/api/**``.
        autostart: Whether ``brainpalace start`` should also bring up the
            dashboard (and open a browser when it launches one). Default True.
        time_format: Clock display format — ``"24h"`` (default) or ``"12h"``.
        date_format: Display date format — ``"dd.mm.yyyy"`` (default),
            ``"mm.dd.yyyy"``, or ``"yyyy-mm-dd"``.
    """

    host: str = "127.0.0.1"
    port: int = 8787
    poll_s: int = 5
    token: str | None = None
    autostart: bool = True
    time_format: str = "24h"
    date_format: str = "dd.mm.yyyy"


def _dashboard_path() -> Path:
    """Path to the dashboard's own config file (separate from server config)."""
    return Path(get_xdg_config_dir()) / "dashboard.yaml"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Persist ``data`` to ``path`` atomically, keeping a ``.bak`` copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    if path.exists():
        path.replace(path.with_suffix(".yaml.bak"))
    os.replace(tmp, path)


def _migrate_legacy_dashboard_block() -> None:
    """One-time move of a legacy ``config.yaml`` ``dashboard:`` block into
    ``dashboard.yaml``. No-op if ``dashboard.yaml`` already exists or there is no
    block. The block is removed from ``config.yaml``; all other sections survive.
    """
    dash = _dashboard_path()
    legacy = get_xdg_config_dir() / "config.yaml"
    if dash.exists() or not legacy.exists():
        return
    data = yaml.safe_load(legacy.read_text()) or {}
    block = data.get("dashboard")
    if not isinstance(block, dict) or not block:
        return
    _atomic_write_yaml(dash, dict(block))
    data.pop("dashboard", None)
    _atomic_write_yaml(legacy, data)


def load_dashboard_config() -> DashboardConfig:
    """Load the dashboard config from ``dashboard.yaml`` (migrating a legacy
    ``config.yaml`` ``dashboard:`` block on first run). All keys optional; unset
    keys fall back to the dataclass defaults.
    """
    _migrate_legacy_dashboard_block()
    cfg = DashboardConfig()
    path = _dashboard_path()
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        cfg.host = str(data.get("host", cfg.host))
        cfg.port = int(data.get("port", cfg.port))
        cfg.poll_s = int(data.get("poll_s", cfg.poll_s))
        token = data.get("token", cfg.token)
        cfg.token = None if token is None else str(token)
        cfg.autostart = bool(data.get("autostart", cfg.autostart))
        tf = str(data.get("time_format", cfg.time_format))
        cfg.time_format = tf if tf in TIME_FORMATS else cfg.time_format
        df = str(data.get("date_format", cfg.date_format))
        cfg.date_format = df if df in DATE_FORMATS else cfg.date_format
    return cfg


def _validate_updates(values: dict[str, Any]) -> list[dict[str, str]]:
    """Validate a partial control-plane settings update. Returns field errors."""
    errors: list[dict[str, str]] = []
    if "port" in values:
        try:
            port = int(values["port"])
            if not (1 <= port <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"field": "port", "message": "port must be 1–65535"})
    if "poll_s" in values:
        try:
            if int(values["poll_s"]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"field": "poll_s", "message": "poll_s must be ≥ 1"})
    if "host" in values and not str(values.get("host") or "").strip():
        errors.append({"field": "host", "message": "host cannot be empty"})
    if "time_format" in values and values["time_format"] not in TIME_FORMATS:
        errors.append(
            {
                "field": "time_format",
                "message": f"time_format must be one of {TIME_FORMATS}",
            }
        )
    if "date_format" in values and values["date_format"] not in DATE_FORMATS:
        errors.append(
            {
                "field": "date_format",
                "message": f"date_format must be one of {DATE_FORMATS}",
            }
        )
    return errors


#: Sparse-savable fields and their coercion (token handled separately).
_SCALAR_FIELDS = ("host", "port", "poll_s", "autostart", "time_format", "date_format")


def _coerce_field(key: str, value: Any) -> Any:
    if key in ("port", "poll_s"):
        return int(value)
    if key == "autostart":
        return bool(value)
    return str(value)


def save_dashboard_config(
    values: dict[str, Any], unset: list[str] | tuple[str, ...] = ()
) -> None:
    """Merge ``values`` into ``dashboard.yaml`` (sparse, atomic).

    Only fields that DIFFER from the :class:`DashboardConfig` default are
    persisted — a field set to its default is dropped so the code default
    applies. ``token`` equal to :data:`TOKEN_MASK` keeps the existing token;
    ``None``/empty clears it. ``unset`` lists fields to REMOVE so they fall back
    to the code default — staged in the form and applied in the same Save (no
    separate immediate /unset call). Raises :class:`DashboardConfigError` on
    validation failure.
    """
    errors = _validate_updates(values)
    if errors:
        raise DashboardConfigError(errors)

    path = _dashboard_path()
    block: dict[str, Any] = {}
    if path.exists():
        block = yaml.safe_load(path.read_text()) or {}

    for field in unset:
        block.pop(field, None)

    for key in _SCALAR_FIELDS:
        if key in values and values[key] is not None:
            block[key] = _coerce_field(key, values[key])
    if "token" in values:
        token = values["token"]
        if token == TOKEN_MASK:
            pass  # keep existing
        elif token is None or str(token).strip() == "":
            block.pop("token", None)
        else:
            block["token"] = str(token)

    # Sparse: drop any field equal to its dataclass default (incl. token == None).
    defaults = DashboardConfig()
    for key in list(block):
        if getattr(defaults, key, object()) == block[key]:
            block.pop(key)

    _atomic_write_yaml(path, block)


#: Every dashboard field, in display order.
_ALL_FIELDS = (
    "host",
    "port",
    "poll_s",
    "token",
    "autostart",
    "time_format",
    "date_format",
)


def _raw_dashboard_block() -> dict[str, Any]:
    path = _dashboard_path()
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def dashboard_config_effective() -> dict[str, dict[str, Any]]:
    """Per-field effective value + provenance (``file`` > code ``default``).

    Single-scope: ``source`` is ``"file"`` (set in dashboard.yaml) or
    ``"default"``. ``token`` is masked — ``TOKEN_MASK`` when set, ``""`` when not —
    so a real token never leaves the server.
    """
    block = _raw_dashboard_block()
    defaults = DashboardConfig()
    out: dict[str, dict[str, Any]] = {}
    for field in _ALL_FIELDS:
        if field in block:
            value, source = block[field], "file"
        else:
            value, source = getattr(defaults, field), "default"
        if field == "token":
            value = TOKEN_MASK if block.get("token") else ""
        out[field] = {"value": value, "source": source}
    return out


def unset_dashboard_config(fields: list[str]) -> dict[str, Any]:
    """Remove fields from ``dashboard.yaml`` so they fall back to code default.

    Returns ``{"removed": [...], "effective": {field: {value, source:"default"}}}``
    — the same shape as the per-instance config unset.
    """
    block = _raw_dashboard_block()
    sentinel = object()
    removed = [f for f in fields if block.pop(f, sentinel) is not sentinel]
    if removed:
        _atomic_write_yaml(_dashboard_path(), block)
    defaults = DashboardConfig()
    now: dict[str, Any] = {}
    for f in fields:
        value = getattr(defaults, f, None)
        if f == "token":
            value = ""  # default token is unset → empty, never a real value
        now[f] = {"value": value, "source": "default"}
    return {"removed": removed, "effective": now}

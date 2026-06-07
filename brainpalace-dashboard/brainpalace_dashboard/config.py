"""Dashboard configuration loader.

Reads the ``dashboard:`` section from the canonical XDG config file
(``$XDG_CONFIG_HOME/brainpalace/config.yaml``, default
``~/.config/brainpalace/config.yaml``). All keys are optional; unset keys fall
back to the dataclass defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml
from brainpalace_cli.xdg_paths import get_xdg_config_dir

#: Returned/accepted in place of a real token so it is never exposed to the SPA.
TOKEN_MASK = "********"


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
    """

    host: str = "127.0.0.1"
    port: int = 8787
    poll_s: int = 5
    token: str | None = None
    autostart: bool = True


def load_dashboard_config() -> DashboardConfig:
    """Load the dashboard config from the XDG config file.

    Returns:
        A :class:`DashboardConfig` populated from the ``dashboard:`` section,
        or all defaults when the file or section is absent.
    """
    cfg = DashboardConfig()
    path = get_xdg_config_dir() / "config.yaml"
    if path.exists():
        data = (yaml.safe_load(path.read_text()) or {}).get("dashboard", {}) or {}
        cfg.host = str(data.get("host", cfg.host))
        cfg.port = int(data.get("port", cfg.port))
        cfg.poll_s = int(data.get("poll_s", cfg.poll_s))
        token = data.get("token", cfg.token)
        cfg.token = None if token is None else str(token)
        cfg.autostart = bool(data.get("autostart", cfg.autostart))
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
    return errors


def save_dashboard_config(values: dict[str, Any]) -> None:
    """Merge ``values`` into the ``dashboard:`` block of the XDG config.yaml.

    Atomic (tmp + ``os.replace``, keeping a ``.bak``). Only the dashboard block
    is touched; every other top-level section is preserved verbatim. A ``token``
    equal to :data:`TOKEN_MASK` keeps the existing token; ``None``/empty clears
    it. Raises :class:`DashboardConfigError` on validation failure.
    """
    errors = _validate_updates(values)
    if errors:
        raise DashboardConfigError(errors)

    path = get_xdg_config_dir() / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    full: dict[str, Any] = {}
    if path.exists():
        full = yaml.safe_load(path.read_text()) or {}
    block: dict[str, Any] = dict(full.get("dashboard") or {})

    for key in ("host", "port", "poll_s"):
        if key in values and values[key] is not None:
            block[key] = (
                int(values[key]) if key in ("port", "poll_s") else str(values[key])
            )
    if "token" in values:
        token = values["token"]
        if token == TOKEN_MASK:
            pass  # keep existing
        elif token is None or str(token).strip() == "":
            block.pop("token", None)
        else:
            block["token"] = str(token)
    if "autostart" in values and values["autostart"] is not None:
        block["autostart"] = bool(values["autostart"])

    full["dashboard"] = block
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(full, sort_keys=False))
    if path.exists():
        path.replace(path.with_suffix(".yaml.bak"))
    os.replace(tmp, path)

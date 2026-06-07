"""Best-effort PyPI update check for the dashboard's "new version" banner.

Queries PyPI for the latest published ``brainpalace-cli`` (the package users
upgrade via ``brainpalace update``) and compares it to the installed version.
The result is cached in-process with a TTL so the SPA can poll cheaply without
hammering PyPI, and every failure path degrades silently to
``update_available: False`` — a flaky network must never break the dashboard.
"""

from __future__ import annotations

import re
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

from brainpalace_dashboard import __version__

# The package users actually install/upgrade. All three brainpalace packages
# share one release train, but this is the one `brainpalace update` targets.
_PACKAGE = "brainpalace-cli"
_PYPI_URL = f"https://pypi.org/pypi/{_PACKAGE}/json"
_TTL_SECONDS = 6 * 3600
_TIMEOUT_SECONDS = 4.0

# In-process cache: the dashboard is a long-running singleton, so a module-level
# cache is enough — no need for a file. (checked_at_monotonic, payload)
_cache: tuple[float, dict[str, Any]] | None = None


def _installed_version() -> str:
    """Installed ``brainpalace-cli`` version, falling back to the dashboard's."""
    try:
        return version(_PACKAGE)
    except PackageNotFoundError:
        return __version__


def _numeric_parts(v: str) -> tuple[int, ...]:
    """Leading numeric components of a version (``"26.6.27" -> (26, 6, 27)``).

    Stops at the first non-numeric token so pre-release/local suffixes don't
    crash the comparison. Good enough for the calendar-style versions used here.
    """
    parts: list[int] = []
    for tok in re.split(r"[.\-+]", v.strip()):
        if tok.isdigit():
            parts.append(int(tok))
        else:
            break
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is a strictly higher version than ``current``."""
    return _numeric_parts(latest) > _numeric_parts(current)


async def _fetch_latest() -> str | None:
    """Fetch the latest published version from PyPI, or None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(_PYPI_URL, headers={"Accept": "application/json"})
            resp.raise_for_status()
            latest = resp.json()["info"]["version"]
            return str(latest) if latest else None
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def get_update_status(*, force: bool = False) -> dict[str, Any]:
    """Return ``{current, latest, update_available, checked_at, ...}`` (cached).

    Never raises — a network/parse failure yields ``update_available: False``
    with ``latest: None`` so the banner simply stays hidden.

    Args:
        force: Bypass the TTL cache and re-query PyPI now.
    """
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and (now - _cache[0]) < _TTL_SECONDS:
        return _cache[1]

    current = _installed_version()
    latest = await _fetch_latest()
    payload: dict[str, Any] = {
        "current": current,
        "latest": latest,
        "update_available": bool(latest and _is_newer(latest, current)),
        "package": _PACKAGE,
        "checked_at": time.time(),
    }
    _cache = (now, payload)
    return payload

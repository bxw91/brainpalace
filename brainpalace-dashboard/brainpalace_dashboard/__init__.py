"""BrainPalace control-plane dashboard."""

import json
from importlib.metadata import distribution

__version__ = "26.6.49"


def _direct_url_is_file(raw: str | None) -> bool:
    """True if a PEP 610 ``direct_url.json`` body records a local ``file://`` URL.

    pip/pipx write this when a package is installed from a local path (the
    dev-install / editable case); a PyPI release has no such record.
    """
    if not raw:
        return False
    try:
        return str(json.loads(raw).get("url", "")).startswith("file://")
    except Exception:
        return False


def _installed_from_source(dist_name: str = "brainpalace-dashboard") -> bool:
    """True when this package was installed from local source rather than a release."""
    try:
        return _direct_url_is_file(distribution(dist_name).read_text("direct_url.json"))
    except Exception:
        return False


def version_display() -> str:
    """Version string for the dashboard footer. Appends ``(from source)`` for a
    local source build, so it is distinguishable from a same-numbered PyPI release.
    Mirrors the CLI's ``--version``; ``__version__`` stays pure for comparisons.
    """
    return f"{__version__} (from source)" if _installed_from_source() else __version__

"""Doc-Serve Server - RAG-based document indexing and query service."""

import json
from importlib.metadata import PackageNotFoundError, distribution, version

# Single source of truth: the version declared in pyproject.toml, read from the
# installed package metadata. Avoids the drift class where pyproject and a
# hardcoded constant disagree (shipped 26.6.1 reporting 26.5.1). __version__ is
# surfaced over HTTP (/health, /runtime, OpenAPI) so the mismatch was visible to
# clients, not just the CLI. Fallback only triggers for an uninstalled checkout.
try:
    __version__ = version("brainpalace-rag")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0+unknown"


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


def _installed_from_source(dist_name: str = "brainpalace-rag") -> bool:
    """True when this package was installed from local source rather than a release."""
    try:
        return _direct_url_is_file(distribution(dist_name).read_text("direct_url.json"))
    except Exception:
        return False


def version_display() -> str:
    """Display version for the /health field (Status tab + ``brainpalace status``).

    Appends ``(from source)`` for a local source build so it is distinguishable
    from a same-numbered PyPI release. Mirrors the CLI's ``--version`` and the
    dashboard footer. ``__version__`` stays pure for any comparison/contract use.
    """
    return f"{__version__} (from source)" if _installed_from_source() else __version__

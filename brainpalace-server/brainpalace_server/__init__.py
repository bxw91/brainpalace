"""Doc-Serve Server - RAG-based document indexing and query service."""

import json
import subprocess
from importlib.metadata import PackageNotFoundError, distribution, version
from urllib.parse import unquote, urlparse

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


def _source_dir(dist_name: str = "brainpalace-rag") -> str | None:
    """Local filesystem path a source build was installed from, or ``None``.

    Reads the ``file://`` URL that pip/pipx records in PEP 610
    ``direct_url.json`` and decodes it to a path.
    """
    try:
        raw = distribution(dist_name).read_text("direct_url.json")
        if not raw:
            return None
        url = str(json.loads(raw).get("url", ""))
        if not url.startswith("file://"):
            return None
        return unquote(urlparse(url).path) or None
    except Exception:
        return None


def _source_git_ref(dist_name: str = "brainpalace-rag") -> str | None:
    """``"<branch> <short-commit>"`` for a source build's git checkout, or ``None``.

    Returns just the commit when the checkout is on a detached HEAD (branch
    resolves to ``HEAD``). ``None`` when the build is not from source, the source
    path is gone, or it is not a git checkout — callers fall back to a plain tag.
    """
    path = _source_dir(dist_name)
    if not path:
        return None
    try:
        branch = subprocess.run(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "-C", path, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return None
    if not commit:
        return None
    return commit if branch in ("", "HEAD") else f"{branch} {commit}"


def _installed_from_source(dist_name: str = "brainpalace-rag") -> bool:
    """True when this package was installed from local source rather than a release."""
    try:
        return _direct_url_is_file(distribution(dist_name).read_text("direct_url.json"))
    except Exception:
        return False


def version_display() -> str:
    """Display version for the /health field (Status tab + ``brainpalace status``).

    For a local source build, appends the build's git ref —
    ``(from <branch> <short-commit>)`` — so it is distinguishable from a
    same-numbered PyPI release and pinpoints the exact built commit; falls back to
    ``(from source)`` when git info is unavailable. Mirrors the CLI's
    ``--version`` and the dashboard footer. ``__version__`` stays pure for any
    comparison/contract use.
    """
    if not _installed_from_source():
        return __version__
    ref = _source_git_ref()
    return f"{__version__} (from {ref})" if ref else f"{__version__} (from source)"

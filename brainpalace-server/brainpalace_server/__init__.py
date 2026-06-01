"""Doc-Serve Server - RAG-based document indexing and query service."""

from importlib.metadata import PackageNotFoundError, version

# Single source of truth: the version declared in pyproject.toml, read from the
# installed package metadata. Avoids the drift class where pyproject and a
# hardcoded constant disagree (shipped 26.6.1 reporting 26.5.1). __version__ is
# surfaced over HTTP (/health, /runtime, OpenAPI) so the mismatch was visible to
# clients, not just the CLI. Fallback only triggers for an uninstalled checkout.
try:
    __version__ = version("brainpalace-rag")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0+unknown"

"""Doc-Serve CLI - Command-line interface for managing Doc-Serve server."""

from importlib.metadata import PackageNotFoundError, version

# Single source of truth: the version declared in pyproject.toml, read from the
# installed package metadata. Avoids the drift class where pyproject and a
# hardcoded constant disagree (shipped 26.6.1 reporting 26.5.1). The fallback
# only triggers for an uninstalled source checkout.
try:
    __version__ = version("brainpalace-cli")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0+unknown"

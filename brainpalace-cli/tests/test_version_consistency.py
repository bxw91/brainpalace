"""Release guard: the two BrainPalace packages must share one version.

This is a CalVer monorepo where `brainpalace-cli` and `brainpalace-rag`
(server) release in lockstep. A bump that touches only one ``pyproject.toml``
ships a mismatched pair. This test fails loudly so the gate catches it before
publish — see ``docs/RELEASING.md`` for the release checklist.

Note on the in-code constant: ``__version__`` is derived from installed package
metadata (``importlib.metadata.version``), so it can no longer drift from
``pyproject.toml`` the way a hardcoded string did (shipped 26.6.1 once reported
26.5.1). The only remaining drift risk is the two pyprojects disagreeing, which
is exactly what this guard covers.
"""

from __future__ import annotations

from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version(rel_path: str) -> str:
    data = tomllib.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    poetry = data.get("tool", {}).get("poetry", {})
    if "version" in poetry:
        return str(poetry["version"])
    return str(data["project"]["version"])


def test_cli_and_server_pyproject_versions_match() -> None:
    """Both packages must declare the same version (lockstep CalVer release)."""
    cli_version = _pyproject_version("brainpalace-cli/pyproject.toml")
    server_version = _pyproject_version("brainpalace-server/pyproject.toml")
    assert cli_version == server_version, (
        f"Version drift: cli={cli_version} server={server_version}. "
        "Bump BOTH pyproject.toml files in lockstep (see docs/RELEASING.md)."
    )

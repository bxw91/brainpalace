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

import json
from pathlib import Path
from typing import Any

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version(rel_path: str) -> str:
    data = tomllib.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    poetry = data.get("tool", {}).get("poetry", {})
    if "version" in poetry:
        return str(poetry["version"])
    return str(data["project"]["version"])


def _json_at(rel_path: str, *keys: Any) -> str:
    """Read a nested value from a JSON file by a path of dict keys / list indexes."""
    node: Any = json.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
    for k in keys:
        node = node[k]
    return str(node)


def test_cli_and_server_pyproject_versions_match() -> None:
    """Both packages must declare the same version (lockstep CalVer release)."""
    cli_version = _pyproject_version("brainpalace-cli/pyproject.toml")
    server_version = _pyproject_version("brainpalace-server/pyproject.toml")
    assert cli_version == server_version, (
        f"Version drift: cli={cli_version} server={server_version}. "
        "Bump BOTH pyproject.toml files in lockstep (see docs/RELEASING.md)."
    )


def _dashboard_module_version() -> str:
    """Read brainpalace_dashboard.__version__ from source (no install needed)."""
    init_path = REPO_ROOT / "brainpalace-dashboard/brainpalace_dashboard/__init__.py"
    for line in init_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("__version__"):
            return line.split("=", 1)[1].split("#", 1)[0].strip().strip("\"'")
    raise AssertionError("brainpalace_dashboard.__version__ not found")


def test_dashboard_version_matches_cli_and_server() -> None:
    """The dashboard ships in lockstep with cli/server — its pyproject and its
    ``__version__`` constant must equal the server version."""
    server_version = _pyproject_version("brainpalace-server/pyproject.toml")
    dashboard_pyproject = _pyproject_version("brainpalace-dashboard/pyproject.toml")
    dashboard_module = _dashboard_module_version()
    assert dashboard_pyproject == server_version, (
        f"Version drift: dashboard pyproject={dashboard_pyproject} "
        f"server={server_version}. Bump all package versions in lockstep "
        "(see docs/RELEASING.md)."
    )
    assert dashboard_module == server_version, (
        f"Version drift: brainpalace_dashboard.__version__={dashboard_module} "
        f"server={server_version}. Keep __init__.py __version__ in lockstep."
    )


def test_plugin_manifest_version_matches_server() -> None:
    """The Claude Code plugin ships in lockstep with cli/server.

    ``plugin.json``'s ``version`` is the freshness key that
    ``plugin_detect.available_plugin_version()`` reads at the latest release tag
    to decide whether the installed plugin is behind. If a release doesn't bump
    it, ``brainpalace plugin status`` / the ``brainpalace update`` tail report
    "up to date" forever — even when the plugin's hooks/skills changed — and the
    user is never offered ``claude plugin update``. Lockstep + this guard prevent
    that.
    """
    server_version = _pyproject_version("brainpalace-server/pyproject.toml")
    plugin_version = _json_at(
        "brainpalace-plugin/.claude-plugin/plugin.json", "version"
    )
    assert plugin_version == server_version, (
        f"Version drift: plugin.json={plugin_version} server={server_version}. "
        "Bump brainpalace-plugin/.claude-plugin/plugin.json in lockstep "
        "(see docs/RELEASING.md) — it drives Claude Code plugin-update detection."
    )


def test_marketplace_plugin_entry_version_matches_server() -> None:
    """The marketplace's plugin entry must match the plugin it lists, so the
    catalog never advertises a stale version. (The marketplace catalog's own
    top-level ``version`` is a separate concept and is not guarded here.)"""
    server_version = _pyproject_version("brainpalace-server/pyproject.toml")
    entry_version = _json_at(".claude-plugin/marketplace.json", "plugins", 0, "version")
    assert entry_version == server_version, (
        f"Version drift: marketplace.json plugin entry={entry_version} "
        f"server={server_version}. Bump the plugins[0].version entry in lockstep "
        "(see docs/RELEASING.md)."
    )

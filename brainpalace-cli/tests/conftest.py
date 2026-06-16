"""Shared CLI test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_global_config(tmp_path_factory, monkeypatch):
    """Empty the GLOBAL (XDG / legacy-home) config layer for every CLI test.

    Config resolves ``project < global < code`` now, and several CLI surfaces
    (``init`` provider-config writes, ``config`` resolution, the dashboard) read
    the global XDG ``config.yaml``. Without isolation the dev machine's real
    ``~/.config/brainpalace/config.yaml`` would leak into test outcomes. Point
    XDG_CONFIG_HOME + HOME at empty temp dirs so the global layer is absent
    unless a test writes one explicitly.
    """
    xdg = tmp_path_factory.mktemp("bp_cli_xdg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # Also isolate the global STATE dir so the instance registry (registry.json)
    # is empty by default — `start`/`find_reusable_server`/reaping read it, and
    # the dev machine's real registry must never leak into a test outcome.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("bp_cli_state")))
    yield
    # Stop any dashboard a test spawned under this tmp state dir. A real daemon
    # spawned via the unmocked dashboard path would otherwise survive the test
    # (orphaned to init), running forever on a climbed port reading the empty
    # tmp registry — the "second dashboard sees no instances" leak. stop_dashboard
    # reaps only same-state-dir strays (list_dashboard_pids is state-scoped), so
    # this never touches the developer's real dashboard.
    try:
        from brainpalace_dashboard import server as _dash  # noqa: PLC0415

        _dash.stop_dashboard()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _pin_server_url(monkeypatch):
    """Pin ``BRAINPALACE_URL`` so command tests never probe the real CWD.

    ``get_server_url()`` walks up from the CWD to ``.brainpalace/`` and, when an
    initialized project owns the directory but no live server validates, raises
    ``ServerNotReachableError`` rather than guess at a URL. ``.brainpalace/`` is
    gitignored, so CI checkouts lack it and the probe falls through harmlessly —
    but a developer's working tree IS an initialized project, so the probe fires
    and every command test that only mocks the API client dies with
    "server isn't reachable". Pinning an explicit URL makes the env-var branch
    win first, so the outcome no longer depends on ambient server state.

    Discovery tests that exercise the resolution order itself
    (``test_server_url_discovery``, ``test_discovery``) clear or set the env via
    their own ``monkeypatch`` in the test body, which runs after this fixture and
    overrides it.
    """
    monkeypatch.setenv("BRAINPALACE_URL", "http://127.0.0.1:8000")

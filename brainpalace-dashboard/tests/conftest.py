"""Shared dashboard test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_xdg(tmp_path_factory, monkeypatch):
    """Point XDG_STATE_HOME + XDG_CONFIG_HOME at empty temp dirs for every test.

    Several dashboard surfaces read the GLOBAL XDG state/config: the instance
    fleet (``registry.json`` / ``known_projects.json``) and the global config
    editor. Without isolation a test inherits the dev machine's real running
    server and indexed data — e.g. ``PATCH /global-config`` walks every live
    instance for the data-compatibility guard and returns 409 against the real
    indexed project, so the test passes only on a clean CI box. Default both XDG
    dirs to empty temps; a test that needs its own state still overrides these
    with its own ``monkeypatch.setenv``.
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("bp_dash_state")))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("bp_dash_cfg")))
    yield

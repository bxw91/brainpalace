"""Shared fixtures for session-adapter tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_adapter_registry():
    """Snapshot/restore the global adapter registry around every test.

    The registry is a module-global; a test that registers a throwaway
    adapter must not leak it into the rest of the run.
    """
    from brainpalace_server.sessions import adapters

    before = dict(adapters._REGISTRY)
    yield
    adapters._REGISTRY.clear()
    adapters._REGISTRY.update(before)

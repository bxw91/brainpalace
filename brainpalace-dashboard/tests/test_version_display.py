"""The dashboard footer (Settings tab) distinguishes a local source build from a
same-numbered PyPI release via PEP 610 install provenance — mirrors the CLI's
`--version (from source)`. The `/settings` endpoint feeds the footer, so it must
report the display string, not the bare number.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import brainpalace_dashboard
from brainpalace_dashboard.app import create_app


def test_direct_url_file_is_source():
    assert brainpalace_dashboard._direct_url_is_file('{"url": "file:///x"}')


def test_direct_url_registry_is_not_source():
    assert not brainpalace_dashboard._direct_url_is_file(
        '{"url": "https://pypi.org/x"}'
    )


def test_direct_url_missing_is_not_source():
    assert not brainpalace_dashboard._direct_url_is_file(None)


def test_version_display_marks_source(monkeypatch):
    monkeypatch.setattr(
        brainpalace_dashboard, "_installed_from_source", lambda *a, **k: True
    )
    assert (
        brainpalace_dashboard.version_display()
        == f"{brainpalace_dashboard.__version__} (from source)"
    )


def test_version_display_plain_for_release(monkeypatch):
    monkeypatch.setattr(
        brainpalace_dashboard, "_installed_from_source", lambda *a, **k: False
    )
    assert brainpalace_dashboard.version_display() == brainpalace_dashboard.__version__


def test_settings_endpoint_reports_version_display(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        brainpalace_dashboard, "_installed_from_source", lambda *a, **k: True
    )
    body = TestClient(create_app()).get("/dashboard/api/settings").json()
    assert body["version"] == f"{brainpalace_dashboard.__version__} (from source)"

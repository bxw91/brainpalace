"""Tests for the optional bearer-token guard on /dashboard/api/**."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from brainpalace_dashboard.app import create_app


def test_no_token_means_no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINPALACE_DASHBOARD_TOKEN", raising=False)
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances")
    assert resp.status_code == 200


def test_token_required_returns_401_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_TOKEN", "abc")
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances")
    assert resp.status_code == 401


def test_token_accepts_correct_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_TOKEN", "abc")
    client = TestClient(create_app())
    resp = client.get(
        "/dashboard/api/instances",
        headers={"Authorization": "Bearer abc"},
    )
    assert resp.status_code == 200


def test_token_rejects_wrong_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_TOKEN", "abc")
    client = TestClient(create_app())
    resp = client.get(
        "/dashboard/api/instances",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_health_is_unguarded_even_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_TOKEN", "abc")
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/health")
    assert resp.status_code == 200


def test_static_is_unguarded_even_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_TOKEN", "abc")
    client = TestClient(create_app())
    # Non-API path (SPA route) must not be guarded; 404 is fine (no build),
    # but it must not be a 401.
    resp = client.get("/dashboard/")
    assert resp.status_code != 401

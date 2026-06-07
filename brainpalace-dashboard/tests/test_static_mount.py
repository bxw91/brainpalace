"""SPA static mount + fallback coexisting with API routers."""

from fastapi.testclient import TestClient

from brainpalace_dashboard.app import create_app


def test_spa_served_at_dashboard_root(tmp_path, monkeypatch) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>BrainPalace</body></html>")
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_STATIC", str(static))
    client = TestClient(create_app())
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert "BrainPalace" in resp.text


def test_spa_fallback_for_client_routes(tmp_path, monkeypatch) -> None:
    """Unknown client-side routes fall back to index.html (SPA routing)."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>SPA-INDEX</body></html>")
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_STATIC", str(static))
    client = TestClient(create_app())
    resp = client.get("/dashboard/instances")
    assert resp.status_code == 200
    assert "SPA-INDEX" in resp.text


def test_static_file_served_directly(tmp_path, monkeypatch) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    (static / "favicon.svg").write_text("<svg/>")
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_STATIC", str(static))
    client = TestClient(create_app())
    resp = client.get("/dashboard/favicon.svg")
    assert resp.status_code == 200
    assert "svg" in resp.text


def test_api_routes_win_over_spa_fallback(tmp_path, monkeypatch) -> None:
    """The catch-all must NOT shadow API routers under /dashboard/api."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>SPA-INDEX</body></html>")
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_STATIC", str(static))
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "SPA-INDEX" not in resp.text


def test_missing_static_dir_is_tolerated(tmp_path, monkeypatch) -> None:
    """When no build is present the app still boots and serves the API."""
    monkeypatch.setenv("BRAINPALACE_DASHBOARD_STATIC", str(tmp_path / "nope"))
    client = TestClient(create_app())
    assert client.get("/dashboard/api/health").status_code == 200
    # No SPA built -> dashboard root should 404 (not crash).
    assert client.get("/dashboard/").status_code == 404

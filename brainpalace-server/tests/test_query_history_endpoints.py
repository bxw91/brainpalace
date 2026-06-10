from fastapi.testclient import TestClient


def test_history_list():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import query as qmod

    sub = FastAPI()

    class FakeLog:
        enabled = True

        def list_recent(self, **kw):
            self.kw = kw
            return [{"id": "1", "query": "x", "mode": "hybrid", "result_count": 2}]

        def get(self, qid):
            return None

    sub.include_router(qmod.router, prefix="/query")
    sub.state.query_log_service = FakeLog()
    c = TestClient(sub)
    r = c.get("/query/history?limit=10&mode=hybrid&contains=x")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "1"


def test_history_list_no_service_returns_empty():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import query as qmod

    sub = FastAPI()
    sub.include_router(qmod.router, prefix="/query")
    c = TestClient(sub)
    r = c.get("/query/history")
    assert r.status_code == 200
    assert r.json() == []


def test_history_detail_ok():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import query as qmod

    sub = FastAPI()

    class FakeLog:
        enabled = True

        def list_recent(self, **kw):
            return []

        def get(self, qid):
            return {"id": qid, "results": [{"path": "a.py"}]}

    sub.include_router(qmod.router, prefix="/query")
    sub.state.query_log_service = FakeLog()
    c = TestClient(sub)
    r = c.get("/query/history/abc")
    assert r.status_code == 200
    assert r.json()["results"][0]["path"] == "a.py"


def test_history_detail_404():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import query as qmod

    sub = FastAPI()

    class FakeLog:
        enabled = True

        def list_recent(self, **kw):
            return []

        def get(self, qid):
            return None

    sub.include_router(qmod.router, prefix="/query")
    sub.state.query_log_service = FakeLog()
    c = TestClient(sub)
    r = c.get("/query/history/missing")
    assert r.status_code == 404


def test_stats_endpoint():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import query as qmod

    sub = FastAPI()

    class FakeLog:
        enabled = True

        def stats(self, **kw):
            self.kw = kw
            return {"total": 7, "mode_distribution": {"hybrid": 7}}

    sub.include_router(qmod.router, prefix="/query")
    sub.state.query_log_service = FakeLog()
    c = TestClient(sub)
    r = c.get("/query/stats?since=123.0&top_n=5")
    assert r.status_code == 200
    assert r.json()["total"] == 7
    assert sub.state.query_log_service.kw == {"since": 123.0, "top_n": 5}


def test_stats_endpoint_no_service_returns_empty_shape():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import query as qmod

    sub = FastAPI()
    sub.include_router(qmod.router, prefix="/query")
    c = TestClient(sub)
    r = c.get("/query/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["top_queries"] == []


def test_health_logs_tail(tmp_path):
    from fastapi import FastAPI

    from brainpalace_server.api.routers import health as hmod

    log_file = tmp_path / "server.log"
    log_file.write_text(
        "\n".join(f"line INFO {i}" for i in range(10)) + "\nWARNING last\n"
    )
    sub = FastAPI()
    sub.include_router(hmod.router, prefix="/health")
    sub.state.log_file_path = str(log_file)
    c = TestClient(sub)
    r = c.get("/health/logs?lines=5")
    assert r.status_code == 200
    assert len(r.json()["lines"]) == 5
    # level filter
    r2 = c.get("/health/logs?level=warning")
    assert any("WARNING" in ln for ln in r2.json()["lines"])


def test_health_logs_no_path():
    from fastapi import FastAPI

    from brainpalace_server.api.routers import health as hmod

    sub = FastAPI()
    sub.include_router(hmod.router, prefix="/health")
    c = TestClient(sub)
    r = c.get("/health/logs")
    assert r.status_code == 200
    assert r.json() == {"lines": []}

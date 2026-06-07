def test_query_logs_after_success():
    """A successful query writes one row to the query log."""
    from brainpalace_server.api.routers import query as qmod

    recorded = {}

    class FakeLog:
        enabled = True

        def record(self, **kw):
            recorded.update(kw)
            return "id1"

    qmod._log_query(
        FakeLog(),
        query="hi",
        mode="hybrid",
        top_k=5,
        latency_ms=3.0,
        results=[{"path": "a"}],
        alpha=0.5,
        filters={},
    )
    assert recorded["query"] == "hi"
    assert recorded["mode"] == "hybrid"


def test_log_query_skips_when_disabled():
    from brainpalace_server.api.routers import query as qmod

    calls = []

    class DisabledLog:
        enabled = False

        def record(self, **kw):
            calls.append(kw)

    qmod._log_query(
        DisabledLog(), query="x", mode="bm25", top_k=1, latency_ms=1.0, results=[]
    )
    assert calls == []


def test_log_query_never_raises():
    from brainpalace_server.api.routers import query as qmod

    class Boom:
        enabled = True

        def record(self, **kw):
            raise RuntimeError("disk full")

    # Must not propagate — logging may never break a query.
    qmod._log_query(Boom(), query="x", mode="bm25", top_k=1, latency_ms=1.0, results=[])
    qmod._log_query(None, query="x", mode="bm25", top_k=1, latency_ms=1.0, results=[])

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


def test_logged_filters_records_all_set_scope_filters():
    """A18 — every scope filter that shaped the query is logged, so a replay
    can reproduce it. Empty filters are omitted; the sensitivity gate never
    appears (it is not a scope filter)."""
    from brainpalace_server.api.routers import query as qmod

    class Req:
        source_types = ["code"]
        languages = ["python"]
        file_paths = ["*dashboard*"]
        domains = None
        metadata_filter = {"owner": "alice"}
        entity_types = []
        relationship_types = ["calls"]
        include_sensitive = True  # must NOT be logged

    logged = qmod._logged_filters(Req())
    assert logged == {
        "source_types": ["code"],
        "languages": ["python"],
        "file_paths": ["*dashboard*"],
        "metadata_filter": {"owner": "alice"},
        "relationship_types": ["calls"],
    }
    assert "include_sensitive" not in logged
    assert "domains" not in logged  # None -> omitted
    assert "entity_types" not in logged  # empty -> omitted


def test_logged_filters_empty_when_unfiltered():
    from brainpalace_server.api.routers import query as qmod

    class Req:
        source_types = None
        languages = None
        file_paths = None
        domains = None
        metadata_filter = None
        entity_types = None
        relationship_types = None

    assert qmod._logged_filters(Req()) == {}

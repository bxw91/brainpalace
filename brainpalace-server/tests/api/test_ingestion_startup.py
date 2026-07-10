def test_reference_catalog_store_constructor_smoke(tmp_path):
    from brainpalace_server.storage.reference_catalog_store import ReferenceCatalogStore

    store = ReferenceCatalogStore(tmp_path / "reference_catalog.db")
    assert store.count() == 0


def test_session_adapter_registered_helper():
    # The startup helper registers the session adapter idempotently.
    from brainpalace_server.ingestion.adapter import known_adapters, reset_adapters
    from brainpalace_server.services.session_records import SessionRecordAdapter

    reset_adapters()
    from brainpalace_server.ingestion.adapter import register_adapter

    register_adapter(SessionRecordAdapter())
    assert any(a.source == "session" for a in known_adapters())
    reset_adapters()

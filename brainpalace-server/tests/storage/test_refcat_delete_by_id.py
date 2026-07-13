from brainpalace_server.storage.reference_catalog_store import (
    ReferenceCatalogStore,
    ReferenceEntry,
    ref_id,
)


def test_delete_by_id_removes_only_named(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "ref.db")
    e1 = ReferenceEntry(
        id=ref_id("/p1", "/s1"),
        domain="d",
        source="/s1",
        source_id="/s1",
        pointer="/p1",
    )
    e2 = ReferenceEntry(
        id=ref_id("/p2", "/s2"),
        domain="d",
        source="/s2",
        source_id="/s2",
        pointer="/p2",
    )
    store.upsert([e1, e2])
    assert store.count() == 2

    n = store.delete_by_id([e1.id, "absent-id"])
    assert n == 1
    remaining = store.list()
    assert [r.id for r in remaining] == [e2.id]

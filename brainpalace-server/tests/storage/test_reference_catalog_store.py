import sqlite3

from brainpalace_server.storage.reference_catalog_store import (
    ReferenceCatalogStore,
    ReferenceEntry,
    ref_id,
)


def _entry(pointer="gmail://msg/1", source="gmail", **kw):
    return ReferenceEntry(
        id=ref_id(pointer, source),
        domain=kw.get("domain", "code"),
        source=source,
        source_id=kw.get("source_id", "acct-1"),
        pointer=pointer,
        summary=kw.get("summary", "an email about X"),
        ingested_at="2026-07-05T00:00:00+00:00",
        properties=kw.get("properties", {}),
        sensitivity=kw.get("sensitivity", "normal"),
    )


_OLD_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reference_catalog (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    source TEXT, source_id TEXT,
    pointer TEXT NOT NULL,
    summary TEXT,
    summary_embedding BLOB,
    ingested_at TEXT,
    properties TEXT
);
CREATE INDEX IF NOT EXISTS idx_refcat_domain ON reference_catalog(domain);
CREATE INDEX IF NOT EXISTS idx_refcat_source ON reference_catalog(source);
"""


def test_upsert_and_list_roundtrip(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    assert store.upsert([_entry()]) == 1
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].pointer == "gmail://msg/1"
    assert rows[0].summary == "an email about X"


def test_upsert_is_idempotent_on_id(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    store.upsert([_entry(summary="v1")])
    store.upsert([_entry(summary="v2")])  # same pointer+source -> same id
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].summary == "v2"


def test_resolve_returns_pointer(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e = _entry()
    store.upsert([e])
    assert store.resolve(e.id) == "gmail://msg/1"
    assert store.resolve("missing") is None


def test_list_filters_by_domain(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    store.upsert(
        [_entry(pointer="p1", domain="code"), _entry(pointer="p2", domain="glasses")]
    )
    assert {r.domain for r in store.list(domain="glasses")} == {"glasses"}


def test_replace_source_is_atomic_swap(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    store.upsert([_entry(pointer="old", source_id="s1")])
    n = store.replace_source("s1", [_entry(pointer="new", source_id="s1")])
    assert n == 1
    pointers = {r.pointer for r in store.list()}
    assert pointers == {"new"}


def test_sensitivity_roundtrips(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    store.upsert([_entry(pointer="p1", sensitivity="private")])
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].sensitivity == "private"


def test_count_unembedded_counts_rows_without_embedding(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    store.upsert([_entry(pointer="p1"), _entry(pointer="p2")])
    assert store.count_unembedded() == 2


def test_set_embeddings_attaches_and_clears_unembedded_count(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e1 = _entry(pointer="p1")
    e2 = _entry(pointer="p2")
    store.upsert([e1, e2])
    n = store.set_embeddings([(e1.id, [0.1, 0.2, 0.3]), (e2.id, [0.4, 0.5, 0.6])])
    assert n == 2
    assert store.count_unembedded() == 0


def test_set_embeddings_does_not_clobber_on_reupsert(tmp_path):
    # Re-upserting a ref (e.g. a summary refresh without an embedder bound)
    # must preserve a previously-stored embedding, not null it out.
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e = _entry(pointer="p1", summary="v1")
    store.upsert([e])
    store.set_embeddings([(e.id, [0.1, 0.2, 0.3])])
    assert store.count_unembedded() == 0

    store.upsert([_entry(pointer="p1", summary="v2")])  # same id, no embedding
    assert store.count_unembedded() == 0


def test_search_summaries_ranks_nearest_first(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e_x = _entry(pointer="px")
    e_y = _entry(pointer="py")
    e_z = _entry(pointer="pz")
    store.upsert([e_x, e_y, e_z])
    # Orthogonal-ish unit vectors.
    store.set_embeddings(
        [
            (e_x.id, [1.0, 0.0, 0.0]),
            (e_y.id, [0.0, 1.0, 0.0]),
            (e_z.id, [0.0, 0.0, 1.0]),
        ]
    )
    hits = store.search_summaries([0.9, 0.1, 0.0], top_k=3)
    # Query points closest to e_x, then e_y; e_z is orthogonal.
    assert [h[0].id for h in hits] == [e_x.id, e_y.id, e_z.id]
    # cosine similarity is in [-1, 1]; nearest is highest.
    assert hits[0][1] >= hits[1][1] >= hits[2][1]


def test_search_summaries_respects_top_k(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e_x = _entry(pointer="px")
    e_y = _entry(pointer="py")
    store.upsert([e_x, e_y])
    store.set_embeddings([(e_x.id, [1.0, 0.0]), (e_y.id, [0.0, 1.0])])
    assert len(store.search_summaries([1.0, 0.0], top_k=1)) == 1


def test_search_summaries_filters_by_domain(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e_a = _entry(pointer="pa", domain="code")
    e_b = _entry(pointer="pb", domain="glasses")
    store.upsert([e_a, e_b])
    store.set_embeddings([(e_a.id, [1.0, 0.0]), (e_b.id, [1.0, 0.0])])
    hits = store.search_summaries([1.0, 0.0], domain="glasses")
    assert [h[0].id for h in hits] == [e_b.id]


def test_search_summaries_excludes_unembedded_rows(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e_a = _entry(pointer="pa")
    e_b = _entry(pointer="pb")  # never embedded
    store.upsert([e_a, e_b])
    store.set_embeddings([(e_a.id, [1.0, 0.0])])
    hits = store.search_summaries([1.0, 0.0], top_k=5)
    assert [h[0].id for h in hits] == [e_a.id]


def test_search_summaries_hides_sensitive_by_default(tmp_path):
    store = ReferenceCatalogStore(tmp_path / "refs.db")
    e_pub = _entry(pointer="ppub", sensitivity="normal")
    e_priv = _entry(pointer="ppriv", sensitivity="private")
    store.upsert([e_pub, e_priv])
    store.set_embeddings([(e_pub.id, [1.0, 0.0]), (e_priv.id, [1.0, 0.0])])

    default_ids = {h[0].id for h in store.search_summaries([1.0, 0.0], top_k=5)}
    assert default_ids == {e_pub.id}

    with_sensitive = {
        h[0].id
        for h in store.search_summaries([1.0, 0.0], top_k=5, include_sensitive=True)
    }
    assert with_sensitive == {e_pub.id, e_priv.id}


def test_old_schema_db_migrates_and_defaults_sensitivity(tmp_path):
    db_path = tmp_path / "old_refs.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_OLD_CREATE_TABLE_SQL)
    conn.execute(
        "INSERT INTO reference_catalog "
        "(id,domain,source,source_id,pointer,summary,summary_embedding,"
        "ingested_at,properties) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "id1",
            "code",
            "gmail",
            "acct-1",
            "gmail://msg/1",
            "an email about X",
            None,
            "2026-07-05T00:00:00+00:00",
            "{}",
        ),
    )
    conn.commit()
    conn.close()

    store = ReferenceCatalogStore(db_path)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].sensitivity == "normal"

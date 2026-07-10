from brainpalace_server.models.record import Record
from brainpalace_server.storage.record_store import RecordStore


def _store(tmp_path):
    return RecordStore(str(tmp_path / "records.db"))


def _rec(rid, value, sensitivity="normal"):
    return Record(
        id=rid,
        subject="proj",
        metric="cost",
        value=value,
        source="s",
        confidence=1.0,
        sensitivity=sensitivity,
    )


def test_column_exists_after_init(tmp_path):
    store = _store(tmp_path)
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(records)")}
    assert "sensitivity" in cols


def test_aggregate_excludes_sensitive_by_default(tmp_path):
    store = _store(tmp_path)
    store.insert_records([_rec("a", 10.0), _rec("b", 5.0, sensitivity="private")])
    rows = store.aggregate(metric="cost", op="sum", min_confidence=0.0)
    assert rows == [(None, 10.0)]  # private row excluded from the total


def test_aggregate_includes_sensitive_when_allowed(tmp_path):
    store = _store(tmp_path)
    store.insert_records([_rec("a", 10.0), _rec("b", 5.0, sensitivity="private")])
    rows = store.aggregate(
        metric="cost", op="sum", min_confidence=0.0, include_sensitive=True
    )
    assert rows == [(None, 15.0)]


def test_legacy_db_migrates(tmp_path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE records (id TEXT PRIMARY KEY, subject TEXT, metric TEXT, "
        "value REAL, unit TEXT, ts TEXT, iso_week TEXT, year_month TEXT, "
        "properties TEXT)"
    )
    conn.commit()
    conn.close()
    store = RecordStore(str(db))  # must not raise; ALTER-adds the column
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(records)")}
    assert "sensitivity" in cols


def test_upsert_updates_sensitivity(tmp_path):
    store = _store(tmp_path)
    store.insert_records([_rec("a", 10.0, sensitivity="normal")])
    rows = store.aggregate(metric="cost", op="sum", min_confidence=0.0)
    assert rows == [(None, 10.0)]
    # re-insert the SAME id with sensitivity="private" via the upsert path
    store.insert_records([_rec("a", 10.0, sensitivity="private")])
    rows = store.aggregate(metric="cost", op="sum", min_confidence=0.0)
    assert rows == [(None, 0.0)]  # now excluded — the mark was updated

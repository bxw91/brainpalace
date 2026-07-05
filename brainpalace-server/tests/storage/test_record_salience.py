from brainpalace_server.models.record import Record
from brainpalace_server.storage.record_store import RecordStore


def _store(tmp_path):
    return RecordStore(tmp_path / "records.db")


def _rec(rid, salience=0.0):
    return Record(id=rid, subject="s", metric="m", value=1.0, salience=salience)


def test_record_has_salience_field():
    assert _rec("a", salience=0.7).salience == 0.7


def test_salience_persisted_and_recomputed(tmp_path):
    store = _store(tmp_path)
    store.insert_records([_rec("a", salience=0.0)])
    n = store.recompute_salience(lambda r: 0.42)
    assert n == 1
    row = store._conn.execute("SELECT salience FROM records WHERE id='a'").fetchone()
    assert row[0] == 0.42


def test_recompute_scorer_sees_domain(tmp_path):
    # Finding B: recompute rebuilds a full Record so a domain-aware scorer works.
    store = _store(tmp_path)
    store.insert_records(
        [Record(id="a", subject="s", metric="m", value=1.0, domain="chat-life")]
    )
    store.recompute_salience(lambda r: 0.9 if r.domain == "chat-life" else 0.0)
    a = store._conn.execute("SELECT salience FROM records WHERE id='a'").fetchone()[0]
    assert a == 0.9


def test_recompute_salience_metric_filter(tmp_path):
    store = _store(tmp_path)
    store.insert_records(
        [
            Record(id="a", subject="s", metric="weight", value=1.0),
            Record(id="b", subject="s", metric="height", value=1.0),
        ]
    )
    n = store.recompute_salience(lambda r: 0.9, metric="weight")
    assert n == 1
    a = store._conn.execute("SELECT salience FROM records WHERE id='a'").fetchone()[0]
    b = store._conn.execute("SELECT salience FROM records WHERE id='b'").fetchone()[0]
    assert a == 0.9 and b == 0.0


def test_salience_column_migration_on_existing_db(tmp_path):
    import sqlite3

    db = tmp_path / "records.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE records (id TEXT PRIMARY KEY, subject TEXT NOT NULL, "
        "metric TEXT NOT NULL, value REAL NOT NULL);"
    )
    conn.commit()
    conn.close()
    store = RecordStore(db)  # must ALTER-add salience, not crash
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(records)")}
    assert "salience" in cols

import sqlite3

from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore

_OLD_SCHEMA = (
    "CREATE TABLE nodes "
    "(id TEXT PRIMARY KEY, name TEXT, label TEXT, properties TEXT);"
    "INSERT INTO nodes VALUES ('n1','Foo','Class','{}');"
)


def test_existing_db_migrates_to_domain_column(tmp_path):
    db = tmp_path / "g.db"
    c = sqlite3.connect(str(db))
    c.executescript(_OLD_SCHEMA)
    c.commit()
    c.close()
    store = SQLitePropertyGraphStore(str(db))  # opening must migrate, not crash
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()}
    assert "domain" in cols
    domain = store._conn.execute("SELECT domain FROM nodes WHERE id='n1'").fetchone()[0]
    assert domain == "code"

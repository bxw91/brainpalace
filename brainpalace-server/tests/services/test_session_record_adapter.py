from types import SimpleNamespace

import pytest

from brainpalace_server.services.session_records import (
    SessionRecordAdapter,
    persist_records,
)
from brainpalace_server.storage.record_store import RecordStore

TS = "2026-07-05T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _pin_salience(monkeypatch):
    # score_salience() -> _age_decay() reads datetime.now() (salience.py:60), so
    # two separate computations (old build vs sink rebuild) differ at the float
    # level and would flake `_rows(old) == _rows(new)`. Force half-life <= 0 so
    # _age_decay returns a constant 1.0 (salience.py:52) — salience deterministic.
    from brainpalace_server.config.settings import settings

    monkeypatch.setattr(
        settings, "BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS", 0, raising=False
    )


def _payload():
    return SimpleNamespace(
        session_id="sess-golden",
        ended_at="2026-07-04T10:00:00+00:00",
        files_touched=["a.py", "b.py"],
        tools_used=["Edit"],
        decisions=["d1"],
        open_threads=[],
        records=[
            SimpleNamespace(
                subject="user",
                metric="coffees",
                value=2.0,
                unit="count",
                ts="2026-07-04T09:00:00+00:00",
            ),
        ],
    )


def _rows(store):
    cur = store._conn.execute(
        "SELECT id,subject,metric,value,unit,ts,domain,source,source_id,"
        "ingested_at,confidence,salience,properties FROM records ORDER BY id"
    )
    return cur.fetchall()


def test_adapter_emits_eager_records_with_session_provenance():
    items = list(SessionRecordAdapter().emit(_payload()))
    assert items, "expected emitted records"
    assert all(i.mode == "eager" for i in items)
    assert all(i.domain == "chat-life" and i.source == "session" for i in items)
    assert all(i.source_id == "sess-golden" for i in items)


def test_golden_rows_identical_via_adapter(tmp_path):
    # Old path: build rows directly (pre-refactor logic, imported helpers).
    from brainpalace_server.services.session_records import (
        derived_count_records,
        records_to_store,
    )

    old_store = RecordStore(tmp_path / "old.db")
    old_recs = derived_count_records(_payload(), ingested_at=TS) + records_to_store(
        _payload(), ingested_at=TS
    )
    old_store.replace_source("sess-golden", old_recs)

    # New path: through the adapter + sink.
    new_store = RecordStore(tmp_path / "new.db")
    persist_records(new_store, _payload(), ingested_at=TS)

    assert _rows(old_store) == _rows(new_store)

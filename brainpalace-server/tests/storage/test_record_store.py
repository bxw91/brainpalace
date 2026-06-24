import pytest

from brainpalace_server.models.record import Record
from brainpalace_server.storage.record_store import RecordStore, derive_buckets


def _rec(id, subject, metric, value, ts, conf=1.0, source="session"):
    return Record(
        id=id,
        subject=subject,
        metric=metric,
        value=value,
        ts=ts,
        confidence=conf,
        source=source,
        source_id="s1",
        domain="chat-life",
    )


@pytest.fixture
def store(tmp_path):
    return RecordStore(tmp_path / "records.db")


def test_derive_buckets_iso_week_and_month():
    assert derive_buckets("2026-01-05T00:00:00") == ("2026-W02", "2026-01")
    assert derive_buckets("not-a-date") == (None, None)
    assert derive_buckets(None) == (None, None)


def test_insert_and_sum(store):
    store.insert_records(
        [
            _rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00"),
            _rec("b", "sales", "amount", 250.0, "2026-01-12T00:00:00"),
        ]
    )
    assert store.aggregate(metric="amount", op="sum") == [(None, 350.0)]


def test_group_by_week_is_iso_and_orders_desc(store):
    store.insert_records(
        [
            _rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00"),  # 2026-W02
            _rec("b", "sales", "amount", 400.0, "2026-01-12T00:00:00"),  # 2026-W03
        ]
    )
    rows = store.aggregate(metric="amount", op="sum", group_by="week")
    assert rows[0] == ("2026-W03", 400.0)


def test_group_by_month(store):
    store.insert_records(
        [
            _rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00"),
            _rec("b", "sales", "amount", 400.0, "2026-02-12T00:00:00"),
        ]
    )
    rows = dict(store.aggregate(metric="amount", op="sum", group_by="month"))
    assert rows == {"2026-01": 100.0, "2026-02": 400.0}


def test_order_asc_and_limit_for_lowest(store):
    store.insert_records(
        [
            _rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00"),
            _rec("b", "sales", "amount", 400.0, "2026-01-12T00:00:00"),
        ]
    )
    rows = store.aggregate(
        metric="amount", op="sum", group_by="week", order="asc", limit=1
    )
    assert rows == [("2026-W02", 100.0)]


def test_unparseable_ts_stored_but_excluded_from_temporal_grouping(store):
    store.insert_records(
        [
            _rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00"),
            _rec("b", "sales", "amount", 9.0, "garbage"),
        ]
    )
    assert store.aggregate(metric="amount", op="sum") == [(None, 109.0)]
    assert store.aggregate(metric="amount", op="sum", group_by="week") == [
        ("2026-W02", 100.0)
    ]


def test_min_confidence_excludes_unverified(store):
    store.insert_records(
        [
            _rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00", conf=1.0),
            _rec("b", "sales", "amount", 999.0, "2026-01-05T00:00:00", conf=0.3),
        ]
    )
    result = store.aggregate(metric="amount", op="sum", min_confidence=0.7)
    assert result == [(None, 100.0)]
    assert store.count_unverified(min_confidence=0.7) == 1


def test_exclude_sources(store):
    store.insert_records(
        [
            _rec(
                "a", "sales", "amount", 100.0, "2026-01-05T00:00:00", source="session"
            ),
            _rec("b", "sales", "amount", 50.0, "2026-01-05T00:00:00", source="email"),
        ]
    )
    result = store.aggregate(metric="amount", op="sum", exclude_sources=["session"])
    assert result == [(None, 50.0)]


def test_delete_by_source_idempotent_reingest(store):
    store.insert_records([_rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00")])
    store.delete_by_source("s1")
    store.insert_records([_rec("a2", "sales", "amount", 200.0, "2026-01-05T00:00:00")])
    assert store.aggregate(metric="amount", op="sum") == [(None, 200.0)]


def test_replace_source_atomic_idempotent(store):
    store.insert_records([_rec("a", "sales", "amount", 100.0, "2026-01-05T00:00:00")])
    store.replace_source(
        "s1", [_rec("a2", "sales", "amount", 200.0, "2026-01-05T00:00:00")]
    )
    assert store.aggregate(metric="amount", op="sum") == [(None, 200.0)]


def test_rejects_bad_op_group_order(store):
    with pytest.raises(ValueError):
        store.aggregate(metric="amount", op="DROP TABLE")
    with pytest.raises(ValueError):
        store.aggregate(metric="amount", op="sum", group_by="x")
    with pytest.raises(ValueError):
        store.aggregate(metric="amount", op="sum", order="x")


def test_revalidate_promotes(store):
    store.insert_records(
        [_rec("a", "weight", "bodyweight", 80.0, "2026-01-05T00:00:00", conf=0.6)]
    )
    assert (
        store.revalidate(
            lambda c: 1.0 if c.metric == "bodyweight" else 0.3, metric="bodyweight"
        )
        == 1
    )
    assert store.aggregate(metric="bodyweight", op="sum", min_confidence=0.7) == [
        (None, 80.0)
    ]

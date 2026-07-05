"""Phase 3 Task 2 — records-store anti-join executor + vocab helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from brainpalace_server.models.record import Record
from brainpalace_server.storage.record_store import RecordStore


def _rec(
    subject: str,
    metric: str,
    *,
    source: str = "session",
    domain: str = "chat-life",
    value: float = 1.0,
    conf: float = 1.0,
    ts: str = "2026-01-05T00:00:00",
) -> Record:
    rid = hashlib.sha1(f"{subject}|{metric}|{source}|{ts}".encode()).hexdigest()[:16]
    return Record(
        id=rid,
        subject=subject,
        metric=metric,
        value=value,
        domain=domain,
        source=source,
        ts=ts,
        confidence=conf,
    )


def _store(tmp_path: Path) -> RecordStore:
    return RecordStore(tmp_path / "r.db")


def test_source_index_created(tmp_path: Path) -> None:
    s = _store(tmp_path)
    names = [
        r[0]
        for r in s._conn.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    ]
    assert "idx_records_source" in names


def test_absent_by_metric(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.insert_records(
        [
            _rec("run", "distance"),
            _rec("run", "duration"),
            _rec("walk", "distance"),  # walk: distance but NOT duration
        ]
    )
    out = s.absent_subjects(
        partition="metric", present_in="distance", absent_from="duration"
    )
    assert out == ["walk"]


def test_confidence_gate_both_sides(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.insert_records(
        [
            _rec("walk", "distance", conf=1.0),
            _rec("walk", "duration", conf=0.3),  # low-conf must NOT fill the gap
        ]
    )
    # walk still counts as absent from duration (its only duration row is < 0.7)
    assert s.absent_subjects(
        partition="metric", present_in="distance", absent_from="duration"
    ) == ["walk"]


def test_source_partition(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.insert_records(
        [
            _rec("release", "note", source="chat"),
            _rec("release", "note", source="gmail"),
            _rec("standup", "note", source="chat"),  # chat only
        ]
    )
    out = s.absent_subjects(partition="source", present_in="chat", absent_from="gmail")
    assert out == ["standup"]


def test_metric_restriction_on_source(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.insert_records(
        [
            _rec("run", "distance", source="chat"),
            _rec("run", "distance", source="gmail"),
            _rec("run", "weight", source="chat"),  # different metric — ignored
        ]
    )
    # restricting to metric=distance: run has distance in both → not absent
    assert (
        s.absent_subjects(
            partition="source",
            present_in="chat",
            absent_from="gmail",
            metric="distance",
        )
        == []
    )


def test_date_range_filters(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.insert_records(
        [
            _rec("run", "distance", ts="2026-01-05T00:00:00"),
            _rec("run", "duration", ts="2026-02-10T00:00:00"),  # outside Jan
        ]
    )
    # within January only, run has distance but not duration → absent
    assert s.absent_subjects(
        partition="metric",
        present_in="distance",
        absent_from="duration",
        since="2026-01-01T00:00:00",
        until="2026-02-01T00:00:00",
    ) == ["run"]


def test_bad_partition_rejected(tmp_path: Path) -> None:
    s = _store(tmp_path)
    try:
        s.absent_subjects(
            partition="value; DROP TABLE records", present_in="a", absent_from="b"
        )
    except ValueError:
        return
    raise AssertionError("expected ValueError for bad partition")


def test_distinct_sources_and_domains(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.insert_records(
        [
            _rec("a", "m", source="session", domain="chat-life"),
            _rec("b", "m", source="gmail", domain="mail"),
        ]
    )
    assert s.distinct_sources() == ["gmail", "session"]
    assert s.distinct_domains() == ["chat-life", "mail"]

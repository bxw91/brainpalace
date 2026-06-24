# tests/eval/test_compute_eval.py
import pytest

from brainpalace_server.models.record import Record
from brainpalace_server.services.compute_compiler import compile_compute
from brainpalace_server.services.query_router import classify_compute_intent
from brainpalace_server.storage.record_store import RecordStore


@pytest.fixture
def seeded(tmp_path):
    rs = RecordStore(tmp_path / "e.db")
    rs.insert_records(
        [
            Record(  # W02 Jan
                id="a",
                subject="sales",
                metric="sales",
                value=100.0,
                ts="2026-01-05T00:00:00",
                confidence=1.0,
            ),
            Record(  # W03 Jan
                id="b",
                subject="sales",
                metric="sales",
                value=400.0,
                ts="2026-01-12T00:00:00",
                confidence=1.0,
            ),
            Record(  # Feb
                id="c",
                subject="sales",
                metric="sales",
                value=50.0,
                ts="2026-02-02T00:00:00",
                confidence=1.0,
            ),
            Record(  # NULL bucket
                id="d",
                subject="sales",
                metric="sales",
                value=9.0,
                ts="garbage",
                confidence=1.0,
            ),
            Record(
                id="e",
                subject="session",
                metric="files_touched",
                value=3.0,
                unit="count",
                ts="2026-01-12T00:00:00",
                confidence=1.0,
            ),
        ]
    )
    return rs


# (query, expected op, group_by, order, expected top-row value)
# superlative-with-group compiles to per-group sum; the top group comes from
# order+limit.
CASES = [
    # W03
    ("which week had the highest sales", "sum", "week", "desc", 400.0),
    # W06 (Feb 2); garbage-ts row excluded from weeks
    ("which week had the lowest sales", "sum", "week", "asc", 50.0),
    # ungrouped: 100+400+50+9
    ("what is the total sales", "sum", None, "desc", 559.0),
    # 4 sales rows (e is files_touched)
    ("how many sales entries", "count", None, "desc", 4.0),
    # Jan = 100+400; garbage-ts excluded
    ("total sales per month", "sum", "month", "desc", 500.0),
]


@pytest.mark.parametrize("q,op,gb,order,top", CASES)
def test_compute_eval(seeded, q, op, gb, order, top):
    assert classify_compute_intent(q)
    plan = compile_compute(q, seeded.distinct_metrics(), seeded.distinct_subjects())
    assert plan is not None and plan.op == op and plan.group_by == gb
    assert plan.order == order
    rows = seeded.aggregate(
        metric=plan.metric,
        op=plan.op,
        group_by=plan.group_by,
        order=plan.order,
        limit=plan.limit,
    )
    assert rows[0][1] == top


def test_subject_paraphrase(seeded):
    plan = compile_compute(
        "how many files did I touch per week",
        seeded.distinct_metrics(),
        seeded.distinct_subjects(),
    )
    assert plan is not None and plan.metric == "files_touched"
    assert plan.group_by == "week"


def test_no_metric_returns_none(seeded):
    assert compile_compute("how is the weather", seeded.distinct_metrics()) is None


def test_persist_transform_has_no_silent_miss():
    """C1 coverage at the transform layer (finding 21): every count field + every
    LLM RecordItem becomes exactly one Record — the transform never silently
    drops a measurement. (Text->RecordItem recall is an LLM property, tracked as
    Phase-4 teaching-loop telemetry, not unit-testable here.)"""
    from brainpalace_server.models.session_extract import (
        FileTouched,
        RecordItem,
        SessionExtraction,
    )
    from brainpalace_server.services.session_records import (
        derived_count_records,
        records_to_store,
    )

    ext = SessionExtraction(
        session_id="s1",
        summary="x",
        ended_at="2026-01-05T00:00:00",
        files_touched=[FileTouched(path="a.py", action="edit")],
        tools_used=["pytest", "git"],
        records=[
            RecordItem(subject="weight", metric="bodyweight", value=80.0, unit="kg"),
            RecordItem(subject="amount", metric="amount", value=10.0, unit="USD"),
        ],
    )
    assert len(derived_count_records(ext, ingested_at="t")) == 4  # all count fields
    # none dropped
    assert len(records_to_store(ext, ingested_at="t")) == len(ext.records)

from brainpalace_server.models.session_extract import (
    FileTouched,
    RecordItem,
    SessionExtraction,
)
from brainpalace_server.services.session_records import (
    derived_count_records,
    records_to_store,
)


def _ext():
    return SessionExtraction(
        session_id="s1",
        summary="did things",
        ended_at="2026-01-05T00:00:00",
        files_touched=[
            FileTouched(path="a.py", action="edit"),
            FileTouched(path="b.py", action="create"),
        ],
        tools_used=["pytest"],
        records=[
            RecordItem(
                subject="amount",
                metric="amount",
                value=4200.0,
                unit="USD",
                ts="2026-01-05T00:00:00",
            ),
            RecordItem(subject="weight", metric="bodyweight", value=80.0, unit="kg"),
        ],
    )


def test_llm_records_confidence_and_provenance():
    by = {r.metric: r for r in records_to_store(_ext(), ingested_at="2026-06-23")}
    assert by["amount"].confidence == 1.0  # authored currency → HIGH
    assert by["bodyweight"].confidence == 0.6  # novel numeric → PROVISIONAL
    assert all(r.domain == "chat-life" and r.source_id == "s1" for r in by.values())


def test_derived_counts_are_high_confidence():
    by = {r.metric: r for r in derived_count_records(_ext(), ingested_at="x")}
    assert by["files_touched"].value == 2.0 and by["files_touched"].confidence == 1.0
    assert by["tools_used"].value == 1.0 and by["files_touched"].unit == "count"


def test_count_record_id_stable_across_redistill():
    a = {r.metric: r.id for r in derived_count_records(_ext(), ingested_at="t1")}
    b = {r.metric: r.id for r in derived_count_records(_ext(), ingested_at="t2")}
    assert a == b  # same session+metric → same id regardless of ingest time/value

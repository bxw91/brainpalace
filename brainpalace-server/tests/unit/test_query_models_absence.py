"""Phase 3 Task 1 — absence mode enum + response models."""

from brainpalace_server.models.query import AbsenceResult, QueryMode, QueryResponse


def test_absence_mode_registered() -> None:
    assert QueryMode.ABSENCE.value == "absence"
    assert QueryMode("absence") is QueryMode.ABSENCE


def test_absence_result_shape() -> None:
    r = AbsenceResult(
        label="walk", present_in="distance", absent_from="duration", partition="metric"
    )
    assert (r.label, r.present_in, r.absent_from, r.partition, r.score) == (
        "walk",
        "distance",
        "duration",
        "metric",
        0.0,
    )


def test_query_response_absence_default_none() -> None:
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    assert resp.absence is None


def test_query_response_carries_absence_rows() -> None:
    rows = [
        AbsenceResult(
            label="walk",
            present_in="distance",
            absent_from="duration",
            partition="metric",
        )
    ]
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=1, absence=rows)
    assert resp.absence is not None and resp.absence[0].label == "walk"

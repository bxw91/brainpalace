"""Phase 4 Task 2 — timeline mode enum + response models."""

from brainpalace_server.models.query import QueryMode, QueryResponse, TimelineResult


def test_timeline_mode_registered() -> None:
    assert QueryMode.TIMELINE.value == "timeline"
    assert QueryMode("timeline") is QueryMode.TIMELINE


def test_timeline_result_shape_defaults() -> None:
    r = TimelineResult(subject="s", predicate="touches", object="cache.py")
    assert (r.subject, r.predicate, r.object) == ("s", "touches", "cache.py")
    assert r.valid_from is None and r.valid_until is None
    assert r.valid is True and r.score == 0.0


def test_timeline_result_carries_validity() -> None:
    r = TimelineResult(
        subject="d1",
        predicate="superseded-by",
        object="d2",
        valid_from="2026-01-01T00:00:00",
        valid_until="2026-03-01T00:00:00",
        valid=False,
    )
    assert r.valid is False and r.valid_until == "2026-03-01T00:00:00"


def test_query_response_timeline_default_none() -> None:
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    assert resp.timeline is None


def test_query_response_carries_timeline_rows() -> None:
    rows = [TimelineResult(subject="d1", predicate="touches", object="f1")]
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=1, timeline=rows)
    assert resp.timeline is not None and resp.timeline[0].predicate == "touches"

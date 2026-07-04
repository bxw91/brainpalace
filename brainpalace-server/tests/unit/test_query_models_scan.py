"""Phase 2 Task 1 — scan mode enum + response models."""

from brainpalace_server.models.query import QueryMode, QueryResponse, ScanResult


def test_scan_mode_registered() -> None:
    assert QueryMode.SCAN.value == "scan"
    assert QueryMode("scan") is QueryMode.SCAN


def test_scan_result_shape() -> None:
    r = ScanResult(label="2026-W03", value=4.0, term="foobar", group="2026-W03")
    assert (r.label, r.value, r.term, r.group, r.score) == (
        "2026-W03",
        4.0,
        "foobar",
        "2026-W03",
        0.0,
    )


def test_query_response_scan_field_default_none() -> None:
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=0)
    assert resp.scan is None


def test_query_response_carries_scan_rows() -> None:
    rows = [ScanResult(label="foobar count", value=7.0, term="foobar")]
    resp = QueryResponse(results=[], query_time_ms=1.0, total_results=1, scan=rows)
    assert resp.scan is not None and resp.scan[0].value == 7.0

from unittest.mock import patch

import pytest

from brainpalace_server.models.query import QueryMode, QueryRequest
from brainpalace_server.models.record import Record
from brainpalace_server.storage.record_store import RecordStore


@pytest.mark.asyncio
async def test_compute_highest_week(tmp_path):
    rs = RecordStore(tmp_path / "r.db")
    rs.insert_records(
        [
            Record(
                id="a",
                subject="sales",
                metric="sales",
                value=100.0,
                ts="2026-01-05T00:00:00",
                confidence=1.0,
            ),
            Record(
                id="b",
                subject="sales",
                metric="sales",
                value=400.0,
                ts="2026-01-12T00:00:00",
                confidence=1.0,
            ),
        ]
    )
    from brainpalace_server.services.query_service import QueryService

    svc = QueryService.__new__(QueryService)
    svc.record_store = rs
    req = QueryRequest(query="which week had the highest sales", mode=QueryMode.COMPUTE)
    results = await svc._execute_compute_query(req)
    assert results and results[0].value == 400.0 and results[0].metric == "sales"


@pytest.mark.asyncio
async def test_compute_empty_when_no_metric(tmp_path):
    rs = RecordStore(tmp_path / "r.db")
    from brainpalace_server.services.query_service import QueryService

    svc = QueryService.__new__(QueryService)
    svc.record_store = rs
    req = QueryRequest(query="how many bugs did I fix", mode=QueryMode.COMPUTE)
    assert await svc._execute_compute_query(req) == []  # → router falls back to hybrid


_SESSION_RECORD = Record(
    id="sess-1",
    subject="sales",
    metric="sales",
    value=200.0,
    ts="2026-01-05T00:00:00",
    confidence=1.0,
    source="session",
    source_id="sess-abc",
)

_COMPUTE_REQ = QueryRequest(
    query="which week had the highest sales", mode=QueryMode.COMPUTE
)


@pytest.mark.asyncio
async def test_compute_excludes_session_records_when_session_hard_off(tmp_path):
    """Compute must exclude source='session' when any session source-type is hidden.

    Privacy parity (Task-11). Regression guard for the no-op exclude bug.
    """
    rs = RecordStore(tmp_path / "r.db")
    rs.insert_records([_SESSION_RECORD])

    from brainpalace_server.services.query_service import QueryService

    svc = QueryService.__new__(QueryService)
    svc.record_store = rs

    # Simulate session hard-off: hidden_session_source_types returns a non-empty set.
    with patch(
        "brainpalace_server.services.query_service.hidden_session_source_types",
        return_value={"session_summary"},
    ):
        results = await svc._execute_compute_query(_COMPUTE_REQ)

    assert (
        results == []
    ), "Session-sourced record must be excluded when session recall is off"


@pytest.mark.asyncio
async def test_compute_includes_session_records_when_session_on(tmp_path):
    """Control: when all session features are on, source='session' records ARE included."""  # noqa: E501
    rs = RecordStore(tmp_path / "r.db")
    rs.insert_records([_SESSION_RECORD])

    from brainpalace_server.services.query_service import QueryService

    svc = QueryService.__new__(QueryService)
    svc.record_store = rs

    # Simulate session fully on: hidden_session_source_types returns empty set.
    with patch(
        "brainpalace_server.services.query_service.hidden_session_source_types",
        return_value=set(),
    ):
        results = await svc._execute_compute_query(_COMPUTE_REQ)

    assert (
        results and results[0].value == 200.0
    ), "Session-sourced record must be included when session recall is on"

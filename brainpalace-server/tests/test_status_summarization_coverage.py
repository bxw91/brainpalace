"""`brainpalace status` session-summarization coverage block."""

from __future__ import annotations

from brainpalace_server.api.routers.health import (
    count_done_markers,
    summarization_coverage,
)


def _mark(project_root, *sids):
    d = project_root / ".brainpalace" / "extracted"
    d.mkdir(parents=True, exist_ok=True)
    for sid in sids:
        (d / f"{sid}.done").write_text("2026-06-04T00:00:00Z")


def test_count_done_markers(tmp_path):
    assert count_done_markers(tmp_path) == 0
    _mark(tmp_path, "a", "b", "c")
    assert count_done_markers(tmp_path) == 3


def test_count_done_markers_empty_root():
    assert count_done_markers("") == 0


def test_coverage_pct(tmp_path):
    _mark(tmp_path, "a", "b")
    cov = summarization_coverage(tmp_path, total_sessions=4, mode="auto")
    assert cov == {
        "mode": "auto",
        "summarized_sessions": 2,
        "total_sessions": 4,
        "summarized_pct": 50.0,
    }


def test_coverage_no_sessions_is_zero(tmp_path):
    cov = summarization_coverage(tmp_path, total_sessions=0, mode="provider")
    assert cov["summarized_pct"] == 0.0
    assert cov["total_sessions"] == 0


def test_coverage_pct_clamped_at_100(tmp_path):
    _mark(tmp_path, "a", "b", "c")  # 3 markers
    cov = summarization_coverage(tmp_path, total_sessions=2, mode="auto")
    assert cov["summarized_pct"] == 100.0  # min(3,2)/2
    assert cov["summarized_sessions"] == 3

"""Q-progress: percent-of-total throttle surfaces every phase marker."""

from brainpalace_server.job_queue.job_worker import _should_persist_progress


def test_completion_always_persists():
    assert (
        _should_persist_progress(
            last_current=50, current=100, total=100, min_percent=2.0
        )
        is True
    )


def test_small_percent_step_below_threshold_is_skipped():
    assert (
        _should_persist_progress(
            last_current=50, current=51, total=100, min_percent=2.0
        )
        is False
    )


def test_phase_marker_jumps_surface():
    assert (
        _should_persist_progress(
            last_current=50, current=90, total=100, min_percent=2.0
        )
        is True
    )


def test_scale_agnostic_for_file_counts():
    assert (
        _should_persist_progress(
            last_current=1000, current=1150, total=10000, min_percent=2.0
        )
        is False
    )
    assert (
        _should_persist_progress(
            last_current=1000, current=1300, total=10000, min_percent=2.0
        )
        is True
    )

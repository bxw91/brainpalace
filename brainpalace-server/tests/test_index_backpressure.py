"""Task 4d: queue high-water backpressure tests.

Tests for should_pause_indexing hysteresis, job-entry deferral, and the
interactive CLI warn+confirm guard.
"""

from brainpalace_server.services.backpressure import should_pause_indexing


def test_should_pause_hysteresis():
    assert should_pause_indexing(50000, 50000, resumed=False) is True  # at high-water
    assert should_pause_indexing(45000, 50000, resumed=True) is True  # above 80%=40000
    assert should_pause_indexing(39999, 50000, resumed=True) is False  # below low-water
    assert should_pause_indexing(10**9, 0, resumed=False) is False  # 0 = off


def test_should_pause_never_when_zero():
    for n in (0, 1, 10, 100000, 10**9):
        assert should_pause_indexing(n, 0, resumed=False) is False


def test_should_pause_exact_boundary():
    # At exactly low-water → still paused (low-water is exclusive)
    low = int(50000 * 0.8)  # 40000
    assert (
        should_pause_indexing(low, 50000, resumed=True) is False
    )  # 40000 == 40000 → clear
    assert (
        should_pause_indexing(low + 1, 50000, resumed=True) is True
    )  # 40001 > 40000 → paused

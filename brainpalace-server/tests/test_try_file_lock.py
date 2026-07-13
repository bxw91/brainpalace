import multiprocessing as mp
from pathlib import Path

from brainpalace_server.locking import try_file_lock


def _hold(lock_path: str, ready, release):
    with try_file_lock(Path(lock_path)):
        ready.set()
        release.wait(5)
    # got is True in the holder


def test_try_file_lock_acquires_when_free(tmp_path):
    with try_file_lock(tmp_path / "r.lock") as got:
        assert got is True


def test_try_file_lock_reports_busy_when_held(tmp_path):
    lock = str(tmp_path / "r.lock")
    ready, release = mp.Event(), mp.Event()
    p = mp.Process(target=_hold, args=(lock, ready, release))
    p.start()
    try:
        assert ready.wait(5)
        with try_file_lock(Path(lock)) as got:
            assert got is False  # someone else holds it
    finally:
        release.set()
        p.join(5)

import threading
import time
from pathlib import Path

from brainpalace_server.locking import file_lock


def test_file_lock_serializes_critical_section(tmp_path: Path):
    lock_path = tmp_path / "r.lock"
    order: list[str] = []

    def worker(tag: str, hold: float):
        with file_lock(lock_path):
            order.append(f"{tag}-enter")
            time.sleep(hold)
            order.append(f"{tag}-exit")

    t1 = threading.Thread(target=worker, args=("A", 0.2))
    t2 = threading.Thread(target=worker, args=("B", 0.0))
    t1.start()
    time.sleep(0.05)  # ensure A grabs the lock first
    t2.start()
    t1.join()
    t2.join()

    # B must not enter between A-enter and A-exit.
    assert order == ["A-enter", "A-exit", "B-enter", "B-exit"]


def test_file_lock_releases_on_exception(tmp_path: Path):
    lock_path = tmp_path / "r.lock"
    try:
        with file_lock(lock_path):
            raise ValueError("boom")
    except ValueError:
        pass
    # Lock must be re-acquirable.
    with file_lock(lock_path):
        pass

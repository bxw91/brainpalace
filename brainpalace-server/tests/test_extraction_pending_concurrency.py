"""Concurrency test for DocPendingStore (finding 2-2).

The store's single SQLite connection is hit by three contexts — the indexer
thread (``mark_pending``), the reconciler event loop (``select_pending`` /
``mark_done``) and FastAPI request handlers. ``check_same_thread=False`` permits
that but gives no write serialization, so every method must take the internal
lock. Without the lock this storm raises ``sqlite3.ProgrammingError`` /
``OperationalError``; with it, it completes cleanly.
"""

from __future__ import annotations

import threading

from brainpalace_server.storage.extraction_pending import DocPendingStore


def test_concurrent_access_does_not_raise(tmp_path):
    store = DocPendingStore(tmp_path / "p.db")
    errors: list[Exception] = []
    n = 200

    def writer(base: str) -> None:
        try:
            for i in range(n):
                store.mark_pending(f"{base}-{i}", f"text-{i}")
        except Exception as exc:  # noqa: BLE001 — capture, assert later
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(n):
                store.select_pending(10)
                store.count_pending()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def doner(base: str) -> None:
        try:
            for i in range(n):
                store.mark_done(f"{base}-{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=("a",)),
        threading.Thread(target=writer, args=("b",)),
        threading.Thread(target=reader),
        threading.Thread(target=doner, args=("a",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent access raised: {errors[:3]}"
    # Still consistent + queryable after the storm.
    assert isinstance(store.count_pending(), int)

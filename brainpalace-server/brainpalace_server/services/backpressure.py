"""Task 4d — queue high-water backpressure.

``should_pause_indexing`` implements hysteresis so the headless indexing
producers (file-watcher, job-worker) pause scheduling new files when the
doc-pending queue is deep, and resume once the drain clears it past the
low-water mark.

Hysteresis prevents rapid on/off flapping:
  - Pause when count >= max_pending  (high-water)
  - Resume when count < low-water    (80% of max_pending)
  - 0 → disabled: never pause.

Callers track the current paused state and pass it as ``resumed=False``
(not yet paused / just resumed) or ``resumed=True`` (currently paused,
checking whether to resume).
"""

from __future__ import annotations


def should_pause_indexing(
    pending_count: int,
    max_pending: int,
    *,
    resumed: bool,
) -> bool:
    """Return True when the indexing producer should pause.

    Args:
        pending_count: Current number of pending extraction items in the queue.
        max_pending:   High-water mark from ``extraction.max_pending``.
                       ``0`` disables backpressure entirely (never pauses).
        resumed:       ``True`` when the caller is currently in a paused state
                       and checking whether to resume (applies the low-water
                       threshold instead of the high-water mark).

    Returns:
        ``True`` when the producer should hold off scheduling new index work;
        ``False`` when it may proceed.
    """
    if max_pending == 0:
        return False  # disabled — never pause

    low_water = int(max_pending * 0.8)

    if resumed:
        # Already paused: resume only when we fall BELOW the low-water mark.
        return pending_count > low_water
    else:
        # Not paused: pause when we reach or exceed the high-water mark.
        return pending_count >= max_pending

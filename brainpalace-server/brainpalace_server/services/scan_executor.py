"""Phase 2 — deterministic map-reduce over the session archive (no LLM).

Counts occurrences of one tokenized term/phrase across archived transcripts,
bucketed by ISO week / month / day / source tool. Pure file IO + the BM25
per-language analyzers — no embeddings, no network, no server state. The
caller (query_service) owns gating (archive on?) and threading
(asyncio.to_thread).

Contract: answers are over the RETAINED archive — retention/eviction shifts
results (documented in docs/SCAN.md).
"""

from __future__ import annotations

import functools
import logging
import multiprocessing
import os
import re
import threading
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import date
from functools import cache
from pathlib import Path

from brainpalace_server.indexing.text_analysis import get_analyzer
from brainpalace_server.services.scan_compiler import ScanPlan

logger = logging.getLogger(__name__)

#: Archive day-folder: YYYY-MM-DD-<tool> (tool suffix optional for tolerance).
_DAY_DIR = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(.+))?$")

#: Below this many files the fixed pool cost dominates. Measured with a warm
#: parent: 1 file seq 0.001s vs pool 0.052s; 12 files seq 0.181s vs pool 0.264s
#: (pool WORSE); 30 files seq 0.533s vs pool 0.285s (1.9x better); 60 files
#: 0.940s vs 0.393s (2.4x). 24 sits just past the measured crossover.
_POOL_MIN_FILES = 24

#: Gains flatten at 8 workers in measurement.
_POOL_MAX_WORKERS = 8

_pool_lock = threading.Lock()
_pool: ProcessPoolExecutor | None = None
_pool_pid: int | None = None


def _pool_width() -> int:
    """Worker count: min(8, CPUs THIS process may actually run on).

    ``sched_getaffinity`` respects cgroup/container CPU limits;
    ``os.cpu_count()`` reports host cores and would oversubscribe a
    constrained container. The latter is only a fallback for platforms
    (macOS, Windows) where affinity is unavailable — and those default to
    the spawn start method, where ``_use_pool`` declines anyway.
    """
    try:
        avail = len(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - non-Linux
        avail = os.cpu_count() or 1
    return max(1, min(_POOL_MAX_WORKERS, avail))


def _use_pool(n_files: int) -> bool:
    """Fan out only when it is measurably worth it AND fork is available.

    The fork gate is not a portability nicety, it is a performance
    requirement. With fork, workers inherit the parent's already-imported
    modules and pool startup is 46-64ms. With spawn, every worker re-imports
    ``brainpalace_server``: 7.56s for 4 workers — worse than the 10.5s
    sequential scan the pool exists to fix. macOS and Windows default to
    spawn, so an ungated pool would make scan dramatically slower there.
    """
    if n_files < _POOL_MIN_FILES:
        return False
    try:
        return multiprocessing.get_start_method(allow_none=False) == "fork"
    except (ValueError, RuntimeError):  # pragma: no cover - defensive
        return False


def _get_pool() -> ProcessPoolExecutor:
    """One lazily-created, reused, pid-guarded pool.

    Lazy + reused (D12): forking from a threaded uvicorn process deadlocks if
    another thread holds a lock at fork time, so fork events are minimized to
    one pool for the process lifetime, which also amortizes startup.

    Pid-guarded (A15): if the server forks after a pool exists, the child
    inherits an executor whose worker processes are not its children. The
    ``os.getpid()`` check makes the child build its own instead.
    """
    global _pool, _pool_pid
    with _pool_lock:
        if _pool is None or _pool_pid != os.getpid():
            _pool = ProcessPoolExecutor(max_workers=_pool_width())
            _pool_pid = os.getpid()
        return _pool


def _reset_pool() -> None:
    """Drop the cached pool (a broken executor never recovers)."""
    global _pool, _pool_pid
    with _pool_lock:
        stale, _pool, _pool_pid = _pool, None, None
    if stale is not None:
        stale.shutdown(wait=False)


def _bucket(day: str, tool: str, group_by: str | None) -> str | None:
    if group_by == "week":
        iso = date.fromisoformat(day).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if group_by == "month":
        return day[:7]
    if group_by == "day":
        return day
    if group_by == "source":
        return tool
    return None


@cache
def _needle(term: str, language: str, engine: str) -> tuple[str, ...]:
    """Analyzed needle tokens, memoized PER PROCESS.

    A file-level fan-out calls this once per file instead of once per scan, so
    without the memo the analyzer lookup + term tokenization (measured at 21%
    of scan cost) would regrow. ``get_analyzer`` itself is already ``@cache``d
    in the registry, so the analyzer object is built at most once per worker
    process; this memo removes the remaining per-file re-tokenization.
    """
    return tuple(get_analyzer(language, engine).analyze(term))


def _count_occurrences(tokens: list[str], needle: list[str]) -> int:
    """Non-overlapping occurrences of the needle token sequence."""
    n = len(needle)
    if n == 0 or n > len(tokens):
        return 0
    count = 0
    i = 0
    while i <= len(tokens) - n:
        if tokens[i : i + n] == needle:
            count += 1
            i += n
        else:
            i += 1
    return count


def _scan_one_file(
    path: Path,
    day: str,
    tool: str,
    plan: ScanPlan,
    language: str,
    engine: str,
    private_ids: frozenset[str],
    include_sensitive: bool,
) -> tuple[str | None, int]:
    """Count ``plan.term`` occurrences in ONE archived session file.

    Module level, not a closure: every argument is a primitive, a frozenset, or
    a frozen pydantic model of primitives, so this is picklable and can be
    dispatched to a process pool.

    ``day``/``tool`` travel WITH the path. Bucket assignment used to be a
    per-day-folder variable that the inner file loop inherited; a file-level
    fan-out that dropped it would collapse every count into a single bucket.
    """
    # Default-deny, BEFORE any read: skip a session whose archive file (named
    # ``<session_id>.jsonl``) is marked private, unless the caller opted in.
    # This must live inside the worker — if the parent fanned out paths and
    # filtered afterwards, private transcripts would be read and counted before
    # exclusion.
    if not include_sensitive and path.stem in private_ids:
        return _bucket(day, tool, plan.group_by), 0

    analyzer = get_analyzer(language, engine)  # process-local @cache, built once
    needle = list(_needle(plan.term, language, engine))
    key = _bucket(day, tool, plan.group_by)
    total = 0
    from brainpalace_server.sessions.parse import parse_transcript

    _, turns = parse_transcript(path, text_trunc=0)
    for t in turns:
        if t.kind != "text" or not t.text:
            continue
        total += _count_occurrences(analyzer.analyze(t.text), needle)
    return key, total


def _run_tasks(
    tasks: list[tuple[Path, str, str]],
    plan: ScanPlan,
    language: str,
    engine: str,
    private_ids: frozenset[str],
    include_sensitive: bool,
) -> list[tuple[str | None, int]]:
    """Per-file (bucket, count) pairs, fanned out when ``_use_pool`` allows.

    Order is irrelevant — the caller only sums into a Counter — so results are
    consumed in whatever order the pool yields them.

    A ``BrokenProcessPool`` (an OOM-killed or crashed worker) is never fatal:
    the executor is dropped and the whole scan is redone sequentially. A scan
    that is slow is strictly better than a scan that raises, and the pool is a
    pure optimization with no semantics of its own.
    """
    work = functools.partial(
        _scan_one_file,
        plan=plan,
        language=language,
        engine=engine,
        private_ids=private_ids,
        include_sensitive=include_sensitive,
    )
    if _use_pool(len(tasks)):
        try:
            pool = _get_pool()
            futures = [pool.submit(work, p, d, t) for p, d, t in tasks]
            return [f.result() for f in futures]
        except BrokenProcessPool:
            logger.warning("scan: worker pool broke, falling back to sequential")
            _reset_pool()
    return [work(p, d, t) for p, d, t in tasks]


def scan_archive(
    archive_dir: Path,
    plan: ScanPlan,
    language: str = "en",
    engine: str = "stem",
    private_session_ids: set[str] | None = None,
    include_sensitive: bool = False,
) -> list[tuple[str | None, int]]:
    """(bucket, count) rows for ``plan`` over the archive; [] when nothing hits."""
    if not archive_dir.is_dir():
        return []
    if not _needle(plan.term, language, engine):
        return []
    private_ids = frozenset(private_session_ids or ())

    # Date-range pruning stays HERE, in the parent: `since`/`until` skip whole
    # day-folders before any IO. Pushing it into per-file work would discard
    # that saving and make bounded queries slower than an unbounded scan.
    tasks: list[tuple[Path, str, str]] = []
    for folder in sorted(archive_dir.iterdir()):
        if not folder.is_dir():
            continue
        m = _DAY_DIR.match(folder.name)
        if not m:
            continue
        day, tool = m.group(1), m.group(2) or "unknown"
        day_iso = f"{day}T00:00:00"
        if plan.since and day_iso < plan.since:
            continue
        if plan.until and day_iso >= plan.until:
            continue
        try:
            _bucket(day, tool, plan.group_by)
        except ValueError:  # malformed date in a hand-made folder name
            continue
        for f in sorted(folder.glob("*.jsonl")):
            tasks.append((f, day, tool))

    pairs = _run_tasks(tasks, plan, language, engine, private_ids, include_sensitive)

    counts: Counter[str | None] = Counter()
    for key, n in pairs:
        if n:
            counts[key] += n

    rows = [(k, v) for k, v in counts.items() if v > 0]
    reverse = plan.order != "asc"
    rows.sort(key=lambda r: (r[1], str(r[0] or "")), reverse=reverse)
    if plan.limit is not None:
        rows = rows[: max(0, plan.limit)]
    return rows

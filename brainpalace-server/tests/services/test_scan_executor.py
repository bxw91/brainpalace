"""Phase 2 Task 4 — pure archive map-reduce executor."""

from __future__ import annotations

import json
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from brainpalace_server.services import scan_executor
from brainpalace_server.services.scan_compiler import ScanPlan
from brainpalace_server.services.scan_executor import scan_archive


def _line(role: str, text: str, ts: str) -> str:
    return json.dumps(
        {
            "type": role,
            "sessionId": "s",
            "timestamp": ts,
            "message": {"role": role, "content": text},
        }
    )


def _archive(tmp_path: Path) -> Path:
    root = tmp_path / "session_archive"
    # 2026-01-05 = ISO week 2026-W02; 2026-01-12 = 2026-W03.
    w2 = root / "2026-01-05-claude-code"
    w3 = root / "2026-01-12-claude-code"
    w2.mkdir(parents=True, exist_ok=True)
    w3.mkdir(parents=True, exist_ok=True)
    (w2 / "a.jsonl").write_text(
        _line("user", "let us discuss foobar today", "2026-01-05T09:00:00Z") + "\n",
        encoding="utf-8",
    )
    (w3 / "b.jsonl").write_text(
        "\n".join(
            [
                _line(
                    "user", "foobar again, and foobar once more", "2026-01-12T09:00:00Z"
                ),
                _line("assistant", "yes: foobar", "2026-01-12T09:01:00Z"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # Non-dir + non-dated entries must be skipped, not crash.
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "not-a-date-dir").mkdir(exist_ok=True)
    return root


def test_weekly_counts(tmp_path: Path) -> None:
    rows = scan_archive(_archive(tmp_path), ScanPlan(term="foobar", group_by="week"))
    assert rows == [("2026-W03", 3), ("2026-W02", 1)]


def test_limit_and_order(tmp_path: Path) -> None:
    top = scan_archive(
        _archive(tmp_path), ScanPlan(term="foobar", group_by="week", limit=1)
    )
    assert top == [("2026-W03", 3)]
    low = scan_archive(
        _archive(tmp_path),
        ScanPlan(term="foobar", group_by="week", order="asc", limit=1),
    )
    assert low == [("2026-W02", 1)]


def test_ungrouped_total(tmp_path: Path) -> None:
    assert scan_archive(_archive(tmp_path), ScanPlan(term="foobar")) == [(None, 4)]


def test_date_range_filters_folders(tmp_path: Path) -> None:
    rows = scan_archive(
        _archive(tmp_path),
        ScanPlan(
            term="foobar",
            group_by="week",
            since="2026-01-10T00:00:00",
            until="2026-02-01T00:00:00",
        ),
    )
    assert rows == [("2026-W03", 3)]


def test_phrase_counting(tmp_path: Path) -> None:
    root = tmp_path / "session_archive"
    d = root / "2026-01-05-claude-code"
    d.mkdir(parents=True)
    (d / "a.jsonl").write_text(
        _line(
            "user",
            "entity resolution beats entity confusion; entity resolution wins",
            "2026-01-05T09:00:00Z",
        )
        + "\n",
        encoding="utf-8",
    )
    rows = scan_archive(root, ScanPlan(term="entity resolution"))
    assert rows == [(None, 2)]


def test_source_bucket(tmp_path: Path) -> None:
    rows = scan_archive(_archive(tmp_path), ScanPlan(term="foobar", group_by="source"))
    assert rows == [("claude-code", 4)]


def test_no_hits_empty(tmp_path: Path) -> None:
    assert scan_archive(_archive(tmp_path), ScanPlan(term="zzzquux")) == []


def test_missing_dir_empty(tmp_path: Path) -> None:
    assert scan_archive(tmp_path / "ghost", ScanPlan(term="foobar")) == []


# --- fan-out: A8 privacy invariant + A10 bucketing under file-level fan-out ---

#: Comfortably above the pool threshold, so these archives take the pooled path
#: wherever the pool is enabled (fork) and the sequential path elsewhere. The
#: assertions are identical either way — that is the point.
_WIDE = 40


def _wide_archive(tmp_path: Path, private_count: int = 0) -> tuple[Path, set[str]]:
    """One day-folder with `_WIDE` sessions, one "widget" occurrence each.

    Returns (archive_root, private_session_ids). The first `private_count`
    sessions are the private ones.
    """
    root = tmp_path / "session_archive"
    day = root / "2026-01-05-claude-code"
    day.mkdir(parents=True)
    private: set[str] = set()
    for i in range(_WIDE):
        sid = f"s{i:03d}"
        (day / f"{sid}.jsonl").write_text(
            _line("user", "widget mentioned here", "2026-01-05T09:00:00Z") + "\n",
            encoding="utf-8",
        )
        if i < private_count:
            private.add(sid)
    return root, private


def test_private_sessions_excluded_under_fanout(tmp_path: Path) -> None:
    """A8: default-deny holds when files are scanned by fanned-out workers.

    The filter must run inside the per-file worker, before the transcript is
    read. If it ever moves back to a post-hoc parent filter, private
    transcripts get read and counted and this count goes to `_WIDE`.
    """
    root, private = _wide_archive(tmp_path, private_count=10)
    plan = ScanPlan(term="widget")

    hidden = scan_archive(root, plan, private_session_ids=private)
    assert hidden == [(None, _WIDE - 10)]

    revealed = scan_archive(
        root, plan, private_session_ids=private, include_sensitive=True
    )
    assert revealed == [(None, _WIDE)]


def test_spawn_platforms_stay_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D10: on a spawn platform the pool is declined and results are unchanged.

    macOS/Windows default to spawn, where each worker re-imports
    `brainpalace_server` and the pool is far slower than scanning inline. The
    gate is only correct if the sequential path returns identical rows, so this
    forces the gate closed on Linux and re-asserts the pooled expectations.
    """
    monkeypatch.setattr(
        scan_executor.multiprocessing, "get_start_method", lambda **kw: "spawn"
    )
    assert scan_executor._use_pool(_WIDE) is False

    root, private = _wide_archive(tmp_path, private_count=10)
    plan = ScanPlan(term="widget")
    assert scan_archive(root, plan, private_session_ids=private) == [(None, _WIDE - 10)]


def test_pool_break_falls_back_to_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed worker degrades to a slow scan, never to an exception."""

    class _BrokenPool:
        def submit(self, *args: object, **kwargs: object) -> object:
            raise BrokenProcessPool("worker died")

    monkeypatch.setattr(scan_executor, "_use_pool", lambda n: True)
    monkeypatch.setattr(scan_executor, "_get_pool", _BrokenPool)

    root, _ = _wide_archive(tmp_path)
    assert scan_archive(root, ScanPlan(term="widget")) == [(None, _WIDE)]


def test_pool_width_is_bounded() -> None:
    assert 1 <= scan_executor._pool_width() <= scan_executor._POOL_MAX_WORKERS


def test_buckets_survive_fanout(tmp_path: Path) -> None:
    """A10: day/tool travel with each path, so counts do not collapse.

    Bucket assignment used to be a per-day-folder variable inherited by the
    inner file loop. Under a file-level fan-out that would give every file the
    last folder's bucket.
    """
    root = tmp_path / "session_archive"
    expected: dict[str, int] = {}
    for day_no, (folder, week) in enumerate(
        [("2026-01-05-claude-code", "2026-W02"), ("2026-01-12-claude-code", "2026-W03")]
    ):
        d = root / folder
        d.mkdir(parents=True)
        n = _WIDE // 2 + day_no  # distinct per-week totals
        for i in range(n):
            (d / f"{folder}-{i:03d}.jsonl").write_text(
                _line("user", "widget once", f"2026-01-0{day_no + 5}T09:00:00Z") + "\n",
                encoding="utf-8",
            )
        expected[week] = n

    rows = scan_archive(root, ScanPlan(term="widget", group_by="week"))
    assert dict(rows) == expected

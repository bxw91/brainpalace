"""Phase 2 Task 4 — pure archive map-reduce executor."""

from __future__ import annotations

import json
from pathlib import Path

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

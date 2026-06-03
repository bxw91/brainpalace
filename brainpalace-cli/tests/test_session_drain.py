"""Tests for the size-throttled, cooldown-paced `drain-queue`."""

from __future__ import annotations

import json
import math

from click.testing import CliRunner

from brainpalace_cli.commands.session_drain import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MAX_COUNT,
    drain_queue,
    drain_queue_command,
    resolve_budget,
    resolve_cooldown,
    resolve_max_count,
    resolve_transcript_size,
    select_batch,
)


# --------------------------------------------------------------------------- #
# select_batch
# --------------------------------------------------------------------------- #
def _sizes(mapping):
    return lambda sid: mapping[sid]


def test_budget_stops_midqueue_fifo():
    ids = ["a", "b", "c", "d"]
    size = _sizes({"a": 400, "b": 400, "c": 400, "d": 400})
    batch, rest = select_batch(ids, size, budget=1000, cap=99)
    assert batch == ["a", "b"]  # 400+400=800 ok; +400=1200 > 1000 → stop
    assert rest == ["c", "d"]


def test_count_cap_before_budget():
    ids = ["a", "b", "c", "d"]
    size = _sizes(dict.fromkeys(ids, 1))
    batch, rest = select_batch(ids, size, budget=10_000, cap=2)
    assert batch == ["a", "b"]
    assert rest == ["c", "d"]


def test_oversized_single_drains_alone_no_starvation():
    ids = ["big", "small"]
    size = _sizes({"big": math.inf, "small": 10})
    batch, rest = select_batch(ids, size, budget=1000, cap=99)
    assert batch == ["big"]  # first-pick-always despite exceeding budget
    assert rest == ["small"]


def test_oversized_not_first_is_left_for_next_turn():
    ids = ["small", "big"]
    size = _sizes({"small": 10, "big": math.inf})
    batch, rest = select_batch(ids, size, budget=1000, cap=99)
    assert batch == ["small"]
    assert rest == ["big"]


def test_empty_ids():
    batch, rest = select_batch([], lambda s: 0, budget=1000, cap=8)
    assert batch == [] and rest == []


# --------------------------------------------------------------------------- #
# resolve_transcript_size
# --------------------------------------------------------------------------- #
def test_size_from_live_dir(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    (live / "s1.jsonl").write_text("x" * 123)
    assert resolve_transcript_size("s1", live, tmp_path / "arch") == 123.0


def test_size_from_archive_fallback(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    arch = tmp_path / "arch"
    nested = arch / "2026-06-04-claude-code"
    nested.mkdir(parents=True)
    (nested / "s2.jsonl").write_text("y" * 50)
    assert resolve_transcript_size("s2", live, arch) == 50.0


def test_size_unresolvable_is_inf(tmp_path):
    assert (
        resolve_transcript_size("nope", tmp_path / "live", tmp_path / "arch")
        == math.inf
    )


# --------------------------------------------------------------------------- #
# drain_queue
# --------------------------------------------------------------------------- #
def _queue(project_root, ids):
    state = project_root / ".brainpalace"
    state.mkdir(parents=True, exist_ok=True)
    (state / "extract-queue.txt").write_text("".join(f"{i}\n" for i in ids))


def _read_queue(project_root):
    q = project_root / ".brainpalace" / "extract-queue.txt"
    return (
        [ln.strip() for ln in q.read_text().splitlines() if ln.strip()]
        if q.exists()
        else []
    )


def test_drain_takes_batch_and_requeues(tmp_path):
    _queue(tmp_path, ["a", "b", "c"])
    live = tmp_path / "live"
    live.mkdir()
    for sid in ("a", "b", "c"):
        (live / f"{sid}.jsonl").write_text("x" * 10)  # tiny → cap is the limiter
    res = drain_queue(
        tmp_path,
        budget=10_000,
        cap=2,
        cooldown=300,
        now=1000.0,
        sessions_dir=live,
        archive_dir=tmp_path / "none",
    )
    assert res["drained"] == ["a", "b"]  # cap=2 hits first
    assert res["remaining"] == 1
    assert _read_queue(tmp_path) == ["c"]
    # last-drain timestamp persisted
    assert (tmp_path / ".brainpalace" / "last-drain").read_text().strip() == "1000.0"


def test_drain_unresolved_sizes_drain_one_at_a_time(tmp_path):
    # No live dir, no archive → every size is inf → only the first drains.
    _queue(tmp_path, ["a", "b", "c"])
    res = drain_queue(
        tmp_path,
        budget=10_000,
        cap=8,
        cooldown=0,
        now=1000.0,
        sessions_dir=tmp_path / "none",
        archive_dir=tmp_path / "none",
    )
    assert res["drained"] == ["a"]
    assert _read_queue(tmp_path) == ["b", "c"]


def test_drain_cooldown_blocks(tmp_path):
    _queue(tmp_path, ["a", "b"])
    (tmp_path / ".brainpalace" / "last-drain").write_text("1000.0")
    res = drain_queue(
        tmp_path,
        budget=10_000,
        cap=8,
        cooldown=300,
        now=1100.0,  # 100s < 300s
        sessions_dir=tmp_path / "none",
        archive_dir=tmp_path / "none",
    )
    assert res["cooldown_active"] is True
    assert res["drained"] == []
    assert res["remaining"] == 2
    assert _read_queue(tmp_path) == ["a", "b"]  # untouched


def test_drain_cooldown_elapsed_proceeds(tmp_path):
    _queue(tmp_path, ["a"])
    (tmp_path / ".brainpalace" / "last-drain").write_text("1000.0")
    res = drain_queue(
        tmp_path,
        budget=10_000,
        cap=8,
        cooldown=300,
        now=1400.0,  # 400s ≥ 300s
        sessions_dir=tmp_path / "none",
        archive_dir=tmp_path / "none",
    )
    assert res["drained"] == ["a"]


def test_drain_cooldown_zero_always_runs(tmp_path):
    _queue(tmp_path, ["a"])
    (tmp_path / ".brainpalace" / "last-drain").write_text("1399.999")
    res = drain_queue(
        tmp_path,
        budget=10_000,
        cap=8,
        cooldown=0,
        now=1400.0,
        sessions_dir=tmp_path / "none",
        archive_dir=tmp_path / "none",
    )
    assert res["drained"] == ["a"]


def test_drain_empty_queue(tmp_path):
    (tmp_path / ".brainpalace").mkdir(parents=True)
    res = drain_queue(
        tmp_path,
        budget=10_000,
        cap=8,
        cooldown=300,
        now=1000.0,
        sessions_dir=tmp_path / "none",
        archive_dir=tmp_path / "none",
    )
    assert res == {"drained": [], "remaining": 0, "cooldown_active": False}


# --------------------------------------------------------------------------- #
# knob resolution
# --------------------------------------------------------------------------- #
def test_knob_defaults(tmp_path):
    assert resolve_budget(tmp_path) == DEFAULT_BUDGET_BYTES
    assert resolve_max_count(tmp_path) == DEFAULT_MAX_COUNT
    assert resolve_cooldown(tmp_path) == DEFAULT_COOLDOWN_SECONDS


def test_knob_from_config(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        "session_extraction:\n"
        "  mode: auto\n"
        "  drain_budget_bytes: 2048\n"
        "  drain_max_count: 3\n"
        "  drain_cooldown_seconds: 60\n"
    )
    assert resolve_budget(tmp_path) == 2048
    assert resolve_max_count(tmp_path) == 3
    assert resolve_cooldown(tmp_path) == 60


def test_knob_env_overrides_config(tmp_path, monkeypatch):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        "session_extraction:\n  drain_budget_bytes: 2048\n"
    )
    monkeypatch.setenv("SESSION_DRAIN_BUDGET_BYTES", "4096")
    assert resolve_budget(tmp_path) == 4096


# --------------------------------------------------------------------------- #
# CLI command
# --------------------------------------------------------------------------- #
def test_command_json_output(tmp_path):
    _queue(tmp_path, ["a", "b"])
    r = CliRunner().invoke(
        drain_queue_command,
        [
            "--project",
            str(tmp_path),
            "--max-count",
            "1",
            "--cooldown-seconds",
            "0",
            "--json",
        ],
    )
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["drained"] == ["a"]
    assert out["remaining"] == 1


def test_command_no_project_is_safe(tmp_path):
    r = CliRunner().invoke(
        drain_queue_command, ["--project", str(tmp_path / "nope"), "--json"]
    )
    assert r.exit_code == 0
    assert json.loads(r.output)["drained"] == []

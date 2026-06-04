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
def _patch_pending(monkeypatch, pairs):
    """Make ``drain_queue`` source its batch from these ``(sid, archive_path)``."""
    from brainpalace_cli.commands import session_drain as sd

    monkeypatch.setattr(sd, "pending_ids", lambda root, now=None: list(pairs))


def _archived(tmp_path, *ids, size=10):
    """Create tiny archived transcripts; return ``[(sid, path), ...]`` FIFO."""
    a = tmp_path / "a"
    a.mkdir(exist_ok=True)
    pairs = []
    for sid in ids:
        f = a / f"{sid}.jsonl"
        f.write_text("x" * size)
        pairs.append((sid, str(f)))
    return pairs


def test_drain_takes_batch_capped(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _archived(tmp_path, "a", "b", "c"))
    res = drain_queue(tmp_path, budget=10_000, cap=2, cooldown=300, now=1000.0)
    assert res["drained"] == ["a", "b"]  # cap=2 hits first
    assert res["remaining"] == 1
    # last-drain timestamp persisted
    assert (tmp_path / ".brainpalace" / "last-drain").read_text().strip() == "1000.0"


def test_drain_unresolved_sizes_drain_one_at_a_time(tmp_path, monkeypatch):
    # Archive paths that don't exist → every size is inf → only the first drains.
    pairs = [(sid, str(tmp_path / "gone" / f"{sid}.jsonl")) for sid in ("a", "b", "c")]
    _patch_pending(monkeypatch, pairs)
    res = drain_queue(tmp_path, budget=10_000, cap=8, cooldown=0, now=1000.0)
    assert res["drained"] == ["a"]
    assert res["remaining"] == 2


def test_drain_cooldown_blocks(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _archived(tmp_path, "a", "b"))
    (tmp_path / ".brainpalace").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".brainpalace" / "last-drain").write_text("1000.0")
    res = drain_queue(tmp_path, budget=10_000, cap=8, cooldown=300, now=1100.0)
    assert res["cooldown_active"] is True
    assert res["drained"] == []
    assert res["remaining"] == 2


def test_drain_cooldown_elapsed_proceeds(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _archived(tmp_path, "a"))
    (tmp_path / ".brainpalace").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".brainpalace" / "last-drain").write_text("1000.0")
    res = drain_queue(tmp_path, budget=10_000, cap=8, cooldown=300, now=1400.0)
    assert res["drained"] == ["a"]


def test_drain_cooldown_zero_always_runs(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _archived(tmp_path, "a"))
    (tmp_path / ".brainpalace").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".brainpalace" / "last-drain").write_text("1399.999")
    res = drain_queue(tmp_path, budget=10_000, cap=8, cooldown=0, now=1400.0)
    assert res["drained"] == ["a"]


def test_drain_no_pending(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, [])
    res = drain_queue(tmp_path, budget=10_000, cap=8, cooldown=300, now=1000.0)
    assert res == {"drained": [], "remaining": 0, "cooldown_active": False}


def test_drain_sources_from_pending_not_queue(tmp_path, monkeypatch):
    # No extract-queue.txt at all; pending comes from the gap selector.
    _patch_pending(monkeypatch, _archived(tmp_path, "s1", "s2"))
    res = drain_queue(tmp_path, budget=10_000, cap=8, cooldown=0, now=1000.0)
    assert res["drained"] == ["s1", "s2"]
    assert res["remaining"] == 0


def test_resolve_quiescence_default(tmp_path):
    from brainpalace_cli.commands.session_drain import resolve_quiescence

    assert resolve_quiescence(tmp_path) == 1800


def test_resolve_quiescence_from_config(tmp_path):
    from brainpalace_cli.commands.session_drain import resolve_quiescence

    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        "session_extraction:\n  quiescence_seconds: 900\n"
    )
    assert resolve_quiescence(tmp_path) == 900


def test_resolve_quiescence_env_overrides(tmp_path, monkeypatch):
    from brainpalace_cli.commands.session_drain import resolve_quiescence

    monkeypatch.setenv("SESSION_QUIESCENCE_SECONDS", "120")
    assert resolve_quiescence(tmp_path) == 120


def test_pending_ids_passes_quiescence(tmp_path, monkeypatch):
    # pending_ids forwards the resolved idle_seconds into the server predicate.
    # The bundled server isn't importable in the CLI test venv, so inject a fake
    # module chain that pending_ids' lazy import resolves to.
    import sys
    import types

    from brainpalace_cli.commands import session_drain as sd

    seen = {}

    def fake_pending(project_root, archive_dir, *, now=None, idle_seconds=None):
        seen["idle"] = idle_seconds
        return []

    distill = types.ModuleType("brainpalace_server.services.session_distill_service")
    distill.pending_sessions = fake_pending  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "brainpalace_server", types.ModuleType("brainpalace_server")
    )
    monkeypatch.setitem(
        sys.modules,
        "brainpalace_server.services",
        types.ModuleType("brainpalace_server.services"),
    )
    monkeypatch.setitem(
        sys.modules, "brainpalace_server.services.session_distill_service", distill
    )
    monkeypatch.setenv("SESSION_QUIESCENCE_SECONDS", "777")
    sd.pending_ids(tmp_path, now=1000.0)
    assert seen["idle"] == 777


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
def test_command_json_output(tmp_path, monkeypatch):
    _patch_pending(monkeypatch, _archived(tmp_path, "a", "b"))
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

"""`backfill-sessions` — both engines (Task 5)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from brainpalace_cli.commands.backfill import (
    backfill_command,
    discover_transcripts,
    enqueue_subagent,
    read_extract_mode,
)


def _project(tmp_path: Path, mode: str) -> Path:
    state = tmp_path / ".brainpalace"
    state.mkdir(parents=True)
    (state / "config.yaml").write_text(f"session_extraction:\n  mode: {mode}\n")
    return tmp_path


def _transcripts(dir_: Path, sids: list[str]) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    for sid in sids:
        (dir_ / f"{sid}.jsonl").write_text('{"type":"user"}\n')
    return dir_


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def test_read_extract_mode_default_provider(tmp_path):
    (tmp_path / ".brainpalace").mkdir()
    assert read_extract_mode(tmp_path) == "provider"


def test_read_extract_mode_off_from_yaml_bool(tmp_path):
    proj = _project(tmp_path, "off")
    assert read_extract_mode(proj) == "off"


def test_discover_transcripts_limit(tmp_path):
    d = _transcripts(tmp_path / "t", ["a", "b", "c"])
    assert len(discover_transcripts(d, limit=2)) == 2


def test_enqueue_subagent_dedups(tmp_path):
    proj = _project(tmp_path, "subagent")
    d = _transcripts(tmp_path / "t", ["s1", "s2"])
    files = discover_transcripts(d, None)
    assert enqueue_subagent(proj, files) == 2
    # Re-running adds nothing (deduped).
    assert enqueue_subagent(proj, files) == 0
    queue = (proj / ".brainpalace" / "extract-queue.txt").read_text().split()
    assert sorted(queue) == ["s1", "s2"]


# --------------------------------------------------------------------------- #
# command
# --------------------------------------------------------------------------- #


def test_subagent_mode_queues(tmp_path):
    proj = _project(tmp_path, "subagent")
    d = _transcripts(tmp_path / "t", ["x1", "x2"])
    result = CliRunner().invoke(
        backfill_command,
        ["--project", str(proj), "--from-dir", str(d), "--json"],
    )
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["mode"] == "subagent"
    assert out["queued"] == 2


def test_provider_mode_calls_distill(tmp_path, monkeypatch):
    proj = _project(tmp_path, "provider")
    d = _transcripts(tmp_path / "t", ["p1", "p2"])

    calls: dict = {}

    class FakeClient:
        def __init__(self, base_url):
            calls["base_url"] = base_url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit_session_distill(self, paths, force=False):
            calls["paths"] = paths
            calls["force"] = force
            return {"enqueued": len(paths), "force": force}

    monkeypatch.setattr("brainpalace_cli.commands.backfill.DocServeClient", FakeClient)
    monkeypatch.setattr(
        "brainpalace_cli.commands.backfill.get_server_url",
        lambda: "http://127.0.0.1:9",
    )
    result = CliRunner().invoke(
        backfill_command,
        ["--project", str(proj), "--from-dir", str(d), "--force", "--json"],
    )
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["mode"] == "provider"
    assert out["enqueued"] == 2
    assert calls["force"] is True
    assert len(calls["paths"]) == 2


def test_auto_mode_with_plugin_uses_subagent(tmp_path, monkeypatch):
    proj = _project(tmp_path, "auto")
    d = _transcripts(tmp_path / "t", ["a1"])
    monkeypatch.setattr(
        "brainpalace_cli.commands.backfill.claude_plugin_installed",
        lambda **k: True,
    )
    r = CliRunner().invoke(
        backfill_command,
        ["--project", str(proj), "--from-dir", str(d), "--json"],
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["mode"] == "subagent"


def test_auto_mode_without_plugin_uses_provider(tmp_path, monkeypatch):
    proj = _project(tmp_path, "auto")
    d = _transcripts(tmp_path / "t", ["a1"])
    monkeypatch.setattr(
        "brainpalace_cli.commands.backfill.claude_plugin_installed",
        lambda **k: False,
    )

    class C:
        def __init__(self, base_url): ...

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit_session_distill(self, paths, force=False):
            return {"enqueued": len(paths), "force": force}

    monkeypatch.setattr("brainpalace_cli.commands.backfill.DocServeClient", C)
    monkeypatch.setattr(
        "brainpalace_cli.commands.backfill.get_server_url",
        lambda: "http://127.0.0.1:9",
    )
    r = CliRunner().invoke(
        backfill_command,
        ["--project", str(proj), "--from-dir", str(d), "--json"],
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["mode"] == "provider"


def test_off_mode_does_nothing(tmp_path):
    proj = _project(tmp_path, "off")
    d = _transcripts(tmp_path / "t", ["z1"])
    result = CliRunner().invoke(
        backfill_command,
        ["--project", str(proj), "--from-dir", str(d), "--json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "off"

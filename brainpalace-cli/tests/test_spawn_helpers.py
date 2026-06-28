import subprocess
import sys
from pathlib import Path

from brainpalace_cli.commands import start


def test_build_server_command_single_source():
    cmd = start.build_server_command("127.0.0.1", 8123)
    assert cmd[0] == sys.executable
    assert "uvicorn" in cmd
    assert "brainpalace_server.api.main:app" in cmd
    assert cmd[cmd.index("--port") + 1] == "8123"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"


def test_uvicorn_argv_has_single_source():
    # Guard: the ``:app`` argv literal must exist exactly once across the CLI —
    # inside build_server_command. No call site may hand-copy the spawn block.
    cli_pkg = Path(start.__file__).resolve().parents[1]
    hits = (
        subprocess.run(
            ["grep", "-rn", "brainpalace_server.api.main:app", str(cli_pkg)],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert len(hits) == 1, f"uvicorn argv must have one source, found: {hits}"
    assert "commands/start.py" in hits[0], hits


def test_rotate_if_oversized_rolls_when_over_cap(tmp_path):
    p = tmp_path / "server.err"
    p.write_text("x" * 200)
    start._rotate_if_oversized(p, max_bytes=100, backups=2)
    # Original rolled away to .1; a fresh append target starts empty.
    assert (tmp_path / "server.err.1").read_text() == "x" * 200
    assert not p.exists() or p.stat().st_size == 0


def test_rotate_if_oversized_keeps_small_file(tmp_path):
    p = tmp_path / "server.err"
    p.write_text("small")
    start._rotate_if_oversized(p, max_bytes=100, backups=2)
    assert p.read_text() == "small"
    assert not (tmp_path / "server.err.1").exists()


def test_rotate_if_oversized_drops_oldest_backup(tmp_path):
    p = tmp_path / "server.err"
    (tmp_path / "server.err.1").write_text("older")
    (tmp_path / "server.err.2").write_text("oldest")
    p.write_text("y" * 200)
    start._rotate_if_oversized(p, max_bytes=100, backups=2)
    # current -> .1, .1 -> .2, previous .2 discarded (backups=2 cap)
    assert (tmp_path / "server.err.1").read_text() == "y" * 200
    assert (tmp_path / "server.err.2").read_text() == "older"

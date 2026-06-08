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

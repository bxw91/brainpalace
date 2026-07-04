# brainpalace-server/tests/lsp/test_client_timeout.py
"""Plan 5 Task 2 — a silent server must not hang the indexing thread."""

import subprocess

import pytest

from brainpalace_server.lsp.client import LspClient, LspError


def test_request_times_out_on_silent_server():
    proc = subprocess.Popen(  # ignores stdin, writes nothing
        ["sleep", "30"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    try:
        client = LspClient(
            reader=proc.stdout, writer=proc.stdin, process=proc, timeout=0.2
        )
        with pytest.raises(LspError, match="timed out"):
            client.request("initialize", {})
    finally:
        proc.kill()
        proc.wait(timeout=5)

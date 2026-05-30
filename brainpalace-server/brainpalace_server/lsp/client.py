"""Minimal synchronous JSON-RPC client for the Language Server Protocol.

Speaks LSP framing (``Content-Length`` header + JSON body) over a pair of binary
streams. Designed to be driven either by a real subprocess (``spawn``) or by
in-memory streams in tests. Single-threaded request/response: ``request`` writes
then reads, skipping notifications/unrelated ids until the matching id arrives.

Deliberately tiny — no async, no full LSP client framework — to keep BrainPalace's
dependency surface minimal (Phase 150 is opt-in and fail-soft).
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import IO, Any

logger = logging.getLogger(__name__)


class LspError(RuntimeError):
    """An LSP error response or transport failure."""


def frame_message(message: dict[str, Any]) -> bytes:
    """Encode a JSON-RPC message with LSP ``Content-Length`` framing."""
    body = json.dumps(message).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def read_message(stream: IO[bytes]) -> dict[str, Any] | None:
    """Read one framed JSON-RPC message. Returns None on EOF."""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None  # EOF
        line = line.rstrip(b"\r\n")
        if line == b"":
            break  # end of headers
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().lower().decode()] = v.strip().decode()
    length = int(headers.get("content-length", 0))
    if length <= 0:
        return None
    body = stream.read(length)
    if len(body) < length:
        return None
    result: dict[str, Any] = json.loads(body.decode("utf-8"))
    return result


class LspClient:
    """Synchronous LSP JSON-RPC client over binary streams."""

    def __init__(
        self,
        reader: IO[bytes],
        writer: IO[bytes],
        process: subprocess.Popen[bytes] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._process = process
        self._id = 0

    @classmethod
    def spawn(cls, cmd: list[str]) -> LspClient:
        """Launch a language server subprocess and wrap its stdio."""
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert proc.stdin is not None and proc.stdout is not None
        return cls(reader=proc.stdout, writer=proc.stdin, process=proc)

    # ------------------------------------------------------------------ I/O
    def _send(self, message: dict[str, Any]) -> None:
        self._writer.write(frame_message(message))
        self._writer.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        self._id += 1
        req_id = self._id
        self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        )
        while True:
            msg = read_message(self._reader)
            if msg is None:
                raise LspError(f"no response to {method!r} (stream closed)")
            if msg.get("id") != req_id:
                # notification or unrelated response — ignore
                continue
            if "error" in msg:
                raise LspError(f"{method}: {msg['error']}")
            return msg.get("result")

    # ------------------------------------------------------------- lifecycle
    def initialize(
        self, root_uri: str, capabilities: dict[str, Any] | None = None
    ) -> Any:
        result = self.request(
            "initialize",
            {
                "processId": None,
                "rootUri": root_uri,
                "capabilities": capabilities or {},
            },
        )
        self.notify("initialized", {})
        return result

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {})
            self.notify("exit", {})
        except Exception as exc:  # noqa: BLE001 — best-effort teardown
            logger.debug("lsp shutdown failed: %s", exc)
        finally:
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    self._process.kill()

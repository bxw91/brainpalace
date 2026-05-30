"""Shared CLI error-handling helpers.

Provides a single exit path for connection errors so every command emits the
same canonical message to stderr and exits with the same code (7 — borrowed
from curl's "couldn't connect to host" convention; distinct from generic 1).
"""

from __future__ import annotations

import json
import sys
from typing import NoReturn

from brainpalace_cli.client.api_client import ConnectionError

EXIT_CODE_CONNECTION_ERROR = 7


def exit_on_connection_error(
    exc: ConnectionError,
    *,
    base_url: str | None = None,
    json_output: bool = False,
) -> NoReturn:
    """Print canonical connection-error message to stderr and exit 7.

    Args:
        exc: The ConnectionError raised by the API client.
        base_url: The URL the CLI tried to reach. Included in the message so
            users can tell which server is unreachable when multiple are
            registered.
        json_output: If True, emit a structured JSON payload to stderr instead
            of human-readable text.

    Exits:
        SystemExit(7) — never returns.
    """
    where = f" at {base_url}" if base_url else ""
    message = (
        f"BrainPalace server not running{where}. " "Run `brainpalace start` to start."
    )

    # Context-sensitive doctor hint (distinguishes "not initialized" from
    # "server down"). Imported lazily to keep this module dependency-light.
    try:
        from brainpalace_cli.diagnostics import doctor_hint_message

        hint = doctor_hint_message()
    except Exception:  # noqa: BLE001 — a hint must never mask the real error
        hint = "Tip: run `brainpalace doctor` to diagnose your setup."

    if json_output:
        payload = {
            "error": "connection_error",
            "url": base_url,
            "message": message,
            "detail": str(exc),
            "hint": hint,
        }
        sys.stderr.write(json.dumps(payload) + "\n")
    else:
        sys.stderr.write(f"Connection Error: {message}\n")
        sys.stderr.write(f"Details: {exc}\n")
        sys.stderr.write(f"{hint}\n")

    raise SystemExit(EXIT_CODE_CONNECTION_ERROR)

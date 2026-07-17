"""Identity-checked server-health probing.

A server being *reachable* (``GET /health/`` returns 200) is not the same
question as a server being *this project's* server. A copied ``.brainpalace/``
folder's ``runtime.json`` can point at a live, healthy server that belongs to
the ORIGINAL project — a bare 200 can't tell the difference, only the
``project_root`` the response carries can.

This module centralizes that identity check as a three-valued probe so
``start``/``list``/``stop`` all agree on what "mine" means. See
``.planning/specs/2026-07-13-identity-checked-server-health.md`` (Part A,
decisions DA1-DA4) for the full rationale.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal
from urllib.request import Request, urlopen

ProbeResult = Literal["mine", "other", "down"]


def fetch_health_body(base_url: str, timeout: float = 3.0) -> dict[str, Any] | None:
    """GET ``{base_url}/health/`` and return the parsed JSON body.

    Returns ``None`` when the server is unreachable, times out, or answers
    with a non-200 status.
    """
    try:
        req = Request(f"{base_url}/health/", method="GET")
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data: dict[str, Any] = json.loads(resp.read())
            return data
    except Exception:
        return None


def check_health(base_url: str, timeout: float = 3.0) -> bool:
    """Reachability only: True iff ``GET {base_url}/health/`` returns 200.

    Does NOT check identity — a bare "something answered" signal for callers
    that only need liveness (e.g. waiting for a just-spawned server to come
    up). Identity-sensitive callers must use :func:`probe` instead.
    """
    return fetch_health_body(base_url, timeout=timeout) is not None


def probe(
    base_url: str,
    expected_root: str | os.PathLike[str],
    timeout: float = 3.0,
) -> ProbeResult:
    """Identity-checked health probe for ``expected_root``.

    Returns:
        - ``"mine"``  — 200 and the response's ``project_root`` (realpath)
          matches ``expected_root`` (realpath); OR the response carries no
          ``project_root`` at all (global/multi mode, or a server too old to
          report it) — degrade safely per DA3: reachable-but-uncheckable is
          treated as ownership, preserving the existing anti-duplicate guard.
        - ``"other"`` — 200 and the response's ``project_root`` is present and
          resolves to a DIFFERENT real path than ``expected_root``. A
          different project answered on this base_url (e.g. a copied
          ``runtime.json`` pointing at the original's live server).
        - ``"down"``  — unreachable, timed out, or a non-200 response.
    """
    data = fetch_health_body(base_url, timeout=timeout)
    if data is None:
        return "down"
    reported_root = data.get("project_root")
    if not reported_root:
        return "mine"
    if os.path.realpath(reported_root) == os.path.realpath(expected_root):
        return "mine"
    return "other"

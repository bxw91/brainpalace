"""Every QueryMode member must be handled by the query service dispatch — catches
'added a mode to the enum, forgot to implement it'.

Heuristic: scans query_service source for a `QueryMode.<NAME>` reference. Coarse
(a bare mention in a comment would false-pass; a dict-based dispatch refactor
would need updating), but cheap and catches the common omission. Tighten only if
the dispatch structure changes."""

import inspect

from brainpalace_server.models.query import QueryMode
from brainpalace_server.services import query_service


def test_every_mode_is_dispatched():
    src = inspect.getsource(query_service)
    missing = [m.name for m in QueryMode if f"QueryMode.{m.name}" not in src]
    assert missing == [], f"modes not handled in query_service: {missing}"

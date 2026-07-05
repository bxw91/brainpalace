"""Register the `query_modes` contract with the generic parity harness.

Source of truth = the server `QueryMode` enum. The five code surfaces that
re-declare the mode set are held equal to it. All extractors import their surface
LAZILY (inside the callable) so importing this module never drags the server
package or the Click app onto a hot path — it is only imported by the parity unit
test and by check_doc_sync.
"""

from __future__ import annotations

from typing import get_args

from brainpalace_cli.doc_sync import contract_parity
from brainpalace_cli.doc_sync.introspect import _extract_modes

MODE_PARITY_SURFACES: tuple[str, ...] = (
    "cli_choice",
    "mcp_literal",
    "hook_guard",
    "mode_meta",
)


def _sot() -> set[str]:
    from brainpalace_server.models.query import QueryMode

    return {m.value for m in QueryMode}


def _cli_choice() -> set[str]:
    from brainpalace_cli.cli import cli  # Click group only

    return set(_extract_modes(cli))


def _mcp_literal() -> set[str]:
    from brainpalace_cli.mcp_server import schemas

    return set(get_args(schemas.QueryMode))


def _hook_guard() -> set[str]:
    from brainpalace_cli.commands import hook

    return set(hook._GUARD_QUERY_MODES)


def _mode_meta() -> set[str]:
    from brainpalace_cli.doc_sync.mode_meta import MODE_META

    return set(MODE_META)


def register_query_modes() -> None:
    contract_parity.register_contract(
        "query_modes",
        sot=_sot,
        surfaces={
            "cli_choice": _cli_choice,
            "mcp_literal": _mcp_literal,
            "hook_guard": _hook_guard,
            "mode_meta": _mode_meta,
        },
    )


def query_modes_mismatches() -> list[contract_parity.ParityMismatch]:
    register_query_modes()
    return contract_parity.check_contract("query_modes")

"""Map Language-Server responses into typed graph triplets (Phase 150).

Given a symbol's position, query the server for call hierarchy, type hierarchy,
and definition, and convert the results into :class:`GraphTriple`s keyed on the
canonical ``file:fqname`` Symbol-Id. Every server call is best-effort: a missing
capability, an error, or a crash yields fewer triplets, never an exception.

LSP ``SymbolKind`` numbers used here: 5 = Class, 11 = Interface.
"""

from __future__ import annotations

import logging
from typing import Any

from brainpalace_server.models.graph import GraphTriple, symbol_id

logger = logging.getLogger(__name__)

_INTERFACE_KIND = 11


def _uri_to_path(uri: str) -> str:
    return (uri or "").removeprefix("file://")


def _item_symbol_id(item: dict[str, Any]) -> str:
    return symbol_id(_uri_to_path(item.get("uri", "")), item.get("name", ""))


def _safe(client: Any, method: str, params: dict[str, Any]) -> Any:
    try:
        return client.request(method, params)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("lsp %s failed: %s", method, exc)
        return None


def extract_cross_refs(
    client: Any,
    *,
    file_path: str,
    symbol_name: str,
    line: int,
    character: int,
    source_chunk_id: str | None = None,
) -> list[GraphTriple]:
    """Produce calls / extends / implements / defined-at triplets for a symbol."""
    me = symbol_id(file_path, symbol_name)
    if not me:
        return []

    uri = f"file://{file_path}"
    pos = {"line": line, "character": character}
    text_doc = {"textDocument": {"uri": uri}, "position": pos}
    triples: list[GraphTriple] = []

    def add(
        subject: str, predicate: str, obj: str, obj_type: str | None = None
    ) -> None:
        if subject and obj:
            triples.append(
                GraphTriple(
                    subject=subject,
                    subject_type="Symbol",
                    predicate=predicate,
                    object=obj,
                    object_type=obj_type,
                    source_chunk_id=source_chunk_id,
                )
            )

    # defined-at
    definition = _safe(client, "textDocument/definition", text_doc)
    for loc in _as_list(definition):
        path = _uri_to_path(loc.get("uri", ""))
        start = (loc.get("range", {}).get("start", {}) or {}).get("line")
        if path and start is not None:
            add(me, "defined-at", f"{path}:{start + 1}", "Location")

    # call hierarchy (incoming + outgoing)
    ch_items = _as_list(_safe(client, "textDocument/prepareCallHierarchy", text_doc))
    if ch_items:
        item = {"item": ch_items[0]}
        for call in _as_list(_safe(client, "callHierarchy/incomingCalls", item)):
            add(_item_symbol_id(call.get("from", {})), "calls", me, "Symbol")
        for call in _as_list(_safe(client, "callHierarchy/outgoingCalls", item)):
            add(me, "calls", _item_symbol_id(call.get("to", {})), "Symbol")

    # type hierarchy (supertypes → extends/implements)
    th_items = _as_list(_safe(client, "textDocument/prepareTypeHierarchy", text_doc))
    if th_items:
        th = {"item": th_items[0]}
        for sup in _as_list(_safe(client, "typeHierarchy/supertypes", th)):
            is_iface = sup.get("kind") == _INTERFACE_KIND
            rel = "implements" if is_iface else "extends"
            add(me, rel, _item_symbol_id(sup), "Symbol")

    return triples


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []

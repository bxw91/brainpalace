"""Map Language-Server responses into typed graph triplets (Phase 150).

Given a symbol's position, query the server for call hierarchy and type
hierarchy, and convert the results into :class:`GraphTriple`s keyed on the
canonical ``file:fqname`` Symbol-Id. Every server call is best-effort: a missing
capability, an error, or a crash yields fewer triplets, never an exception.

LSP ``SymbolKind`` numbers used here: 5 = Class, 11 = Interface.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from brainpalace_server.models.graph import GraphTriple, symbol_id

logger = logging.getLogger(__name__)

_INTERFACE_KIND = 11


def _uri_to_path(uri: str) -> str:
    return (uri or "").removeprefix("file://")


def _short(canonical_id: str) -> str:
    """Short display name from a `file:fqname` id (or a `path:line` location)."""
    tail = (canonical_id or "").rsplit(":", 1)[-1]
    return tail.split(".")[-1] if "." in tail else tail


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
    target_fqname: Callable[[str, int, str], str] | None = None,
) -> list[GraphTriple]:
    """Produce calls / extends / implements / defined-at triplets for a symbol."""
    me = symbol_id(file_path, symbol_name)
    if not me:
        return []

    def item_id(item: dict[str, Any]) -> str:
        path = _uri_to_path(item.get("uri", ""))
        name = item.get("name", "")
        start = ((item.get("range") or {}).get("start") or {}).get("line")
        if target_fqname is not None and path and start is not None:
            name = target_fqname(path, int(start), name)
        return symbol_id(path, name)

    uri = f"file://{file_path}"
    pos = {"line": line, "character": character}
    text_doc = {"textDocument": {"uri": uri}, "position": pos}
    triples: list[GraphTriple] = []

    def add(
        subj_id: str, predicate: str, obj_id: str, obj_type: str | None = None
    ) -> None:
        if subj_id and obj_id:
            triples.append(
                GraphTriple(
                    subject=subj_id,
                    subject_type="Symbol",
                    predicate=predicate,
                    object=obj_id,
                    object_type=obj_type,
                    subject_id=subj_id,
                    object_id=obj_id,
                    subject_name=_short(subj_id),
                    object_name=_short(obj_id),
                    source_chunk_id=source_chunk_id,
                )
            )

    # call hierarchy (incoming + outgoing)
    ch_items = _as_list(_safe(client, "textDocument/prepareCallHierarchy", text_doc))
    if ch_items:
        item = {"item": ch_items[0]}
        for call in _as_list(_safe(client, "callHierarchy/incomingCalls", item)):
            add(item_id(call.get("from", {})), "calls", me, "Symbol")
        for call in _as_list(_safe(client, "callHierarchy/outgoingCalls", item)):
            add(me, "calls", item_id(call.get("to", {})), "Symbol")

    # type hierarchy (supertypes → extends/implements)
    th_items = _as_list(_safe(client, "textDocument/prepareTypeHierarchy", text_doc))
    if th_items:
        th = {"item": th_items[0]}
        for sup in _as_list(_safe(client, "typeHierarchy/supertypes", th)):
            is_iface = sup.get("kind") == _INTERFACE_KIND
            rel = "implements" if is_iface else "extends"
            add(me, rel, item_id(sup), "Symbol")

    return triples


def extract_reference(
    client: Any,
    *,
    file_path: str,
    caller_id: str,
    name: str,
    line: int,
    character: int,
    source_chunk_id: str | None = None,
) -> GraphTriple | None:
    """One ``references`` triple for a non-call type-use site, or None (§5b).

    ``textDocument/definition`` at the site gives the exact defining file;
    the referenced symbol id is keyed on that file + the site's own short
    name, matching the AST layer's ``file:fqname`` scheme. LSP-only — the
    caller never emits a references edge without a definition hit.
    """
    if not caller_id:
        return None
    params = {
        "textDocument": {"uri": f"file://{file_path}"},
        "position": {"line": line, "character": character},
    }
    for loc in _as_list(_safe(client, "textDocument/definition", params)):
        target_path = _uri_to_path(loc.get("uri", ""))
        if not target_path:
            continue
        short = name.rsplit(".", 1)[-1]
        obj_id = symbol_id(target_path, short)
        if not obj_id or obj_id == caller_id:
            continue
        return GraphTriple(
            subject=caller_id,
            subject_type="Symbol",
            predicate="references",
            object=obj_id,
            object_type="Symbol",
            subject_id=caller_id,
            object_id=obj_id,
            subject_name=_short(caller_id),
            object_name=short,
            source_chunk_id=source_chunk_id,
        )
    return None


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []

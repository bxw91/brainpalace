"""Knowledge-graph browse endpoints (dashboard graph browser)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from brainpalace_server.config import settings
from brainpalace_server.models.graph import RELATIONSHIP_TYPES
from brainpalace_server.storage.graph_store import (
    GraphStoreManager,
    get_graph_store_manager,
)

router = APIRouter()


def _graph_manager() -> GraphStoreManager:
    """Return the graph store manager, ready to read.

    503s when graph indexing is disabled. Calls ``initialize()`` (idempotent,
    a no-op when disabled) so the browse endpoints work on a freshly started
    server: counts come from the ``graph_metadata.json`` sidecar without
    loading the store, so without this the store stays lazy (``None``) and
    every browse query returns empty even though entities exist on disk.
    """
    if not settings.ENABLE_GRAPH_INDEX:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph indexing is disabled (set graph_indexing.enabled: true "
            "in config.yaml, and ENABLE_GRAPH_INDEX is not false).",
        )
    mgr = get_graph_store_manager()
    mgr.initialize()
    return mgr


_VALID_DOMAINS = {"code", "doc", "session", "git"}


def _parse_domains(domains: str | None) -> list[str] | None:
    """CSV domains facet → validated list; None = unfiltered (back-compat)."""
    if not domains:
        return None
    parts = [p.strip() for p in domains.split(",") if p.strip()]
    bad = sorted(set(parts) - _VALID_DOMAINS)
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown domain(s): {', '.join(bad)} "
            f"(valid: {', '.join(sorted(_VALID_DOMAINS))})",
        )
    return parts or None


_AMBIGUITY_LOOKUP_LIMIT = 5


def _resolve_ref(mgr: GraphStoreManager, ref: str) -> str:
    """Node id for ``ref``: exact id first, then UNIQUE exact display name."""
    node = mgr.get_node(ref)
    if node is not None:
        return str(node["id"])
    hits = mgr.nodes_by_exact_name(ref, limit=_AMBIGUITY_LOOKUP_LIMIT)
    if len(hits) == 1:
        return str(hits[0]["id"])
    if len(hits) > 1:
        ids = ", ".join(str(h["id"]) for h in hits)
        if len(hits) == _AMBIGUITY_LOOKUP_LIMIT:
            ids += ", …"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ambiguous name {ref!r}: " + ids + " — pass a node id",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown node {ref!r}"
    )


def _parse_predicates(predicates: str | None) -> list[str] | None:
    if not predicates:
        return None
    parts = [p.strip() for p in predicates.split(",") if p.strip()]
    bad = sorted(set(parts) - set(RELATIONSHIP_TYPES))
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown predicate(s): {', '.join(bad)} "
            f"(valid: {', '.join(RELATIONSHIP_TYPES)})",
        )
    return parts or None


@router.get(
    "/nodes",
    summary="Search graph nodes",
    description="Name-substring entity search with active-edge degree; the "
    "seed picker for the dashboard graph browser. 503 when graph indexing "
    "is disabled.",
)
async def search_nodes(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    domains: str | None = Query(
        None, description="CSV domain facet (code,doc,session,git); absent = all."
    ),
) -> dict[str, Any]:
    mgr = _graph_manager()
    return {"nodes": mgr.search_nodes(q, limit=limit, domains=_parse_domains(domains))}


@router.get(
    "/top",
    summary="Highest-degree hub nodes",
    description="Most-connected entities (active-edge degree), no search "
    "needed — seeds the dashboard graph browser on open. 503 when graph "
    "indexing is disabled.",
)
async def top_nodes(
    limit: int = Query(20, ge=1, le=100),
    domains: str | None = Query(
        None, description="CSV domain facet (code,doc,session,git); absent = all."
    ),
) -> dict[str, Any]:
    mgr = _graph_manager()
    return {"nodes": mgr.top_nodes(limit=limit, domains=_parse_domains(domains))}


@router.get(
    "/neighbors",
    summary="Expand one node's neighborhood",
    description="Active edges touching the node plus every connected node — "
    "one expand step of the seed/expand browser. 503 when graph indexing "
    "is disabled.",
)
async def neighbors(
    node: str = Query(..., min_length=1),
    limit: int = Query(200, ge=1, le=500),
    domains: str | None = Query(
        None, description="CSV domain facet (code,doc,session,git); absent = all."
    ),
) -> dict[str, Any]:
    mgr = _graph_manager()
    return mgr.neighbors([node], limit=limit, domains=_parse_domains(domains))


_MAX_SOURCE_BYTES = 2_000_000


@router.get(
    "/node/source",
    summary="Source snippet for a graph node",
    description="Lines around the node's recorded definition position. The "
    "path comes from the node's stored properties (or a File node's id) — "
    "never from the client. 404 when the node has no recorded location or "
    "the file is gone; 503 when graph indexing is disabled.",
)
async def node_source(
    node: str = Query(..., min_length=1),
    context: int = Query(20, ge=0, le=200),
) -> dict[str, Any]:
    mgr = _graph_manager()
    info = mgr.get_node(node)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown node"
        )
    props = info.get("properties") or {}
    path = props.get("path")
    line = props.get("line", 0)
    if not path and info.get("label") == "File" and info.get("domain") == "code":
        path, line = info["id"], 0
    if not isinstance(path, str) or not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="node has no recorded source location",
        )
    p = Path(path)
    if not p.is_absolute() or not p.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="source file not found"
        )
    if p.stat().st_size > _MAX_SOURCE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="source file too large"
        )
    lines = p.read_text(errors="replace").splitlines()
    ln = min(max(int(line or 0), 0), max(len(lines) - 1, 0))
    start = max(0, ln - context)
    end = min(len(lines), ln + context + 1)
    return {
        "path": str(p),
        "line": ln,
        "start_line": start,
        "lines": lines[start:end],
    }


@router.get(
    "/path",
    summary="Shortest paths between two graph nodes",
    description="Level-synchronous BFS over currently-valid edges, walked in "
    "either direction (each hop reports the stored direction). src/dst accept "
    "a node id or a unique exact display name. 503 when graph indexing is "
    "disabled.",
)
async def find_path(
    src: str = Query(..., min_length=1),
    dst: str = Query(..., min_length=1),
    max_depth: int = Query(6, ge=1, le=10),
    limit: int = Query(5, ge=1, le=20),
    domains: str | None = Query(
        None, description="CSV domain facet (code,doc,session,git); absent = all."
    ),
) -> dict[str, Any]:
    mgr = _graph_manager()
    src_id = _resolve_ref(mgr, src)
    dst_id = _resolve_ref(mgr, dst)
    out = mgr.find_paths(
        src_id,
        dst_id,
        max_depth=max_depth,
        limit=limit,
        domains=_parse_domains(domains),
    )
    return {"src": src_id, "dst": dst_id, **out}


@router.get(
    "/impact",
    summary="Impact analysis — what depends on a node",
    description="Reverse closure over dependency predicates (calls, imports, "
    "references, depends_on, handled_by, extends, implements, decorated_by, "
    "defined_in by default): every node that transitively depends on the "
    "given one, shallowest first. 503 when graph indexing is disabled.",
)
async def impact(
    node: str = Query(..., min_length=1),
    max_depth: int = Query(3, ge=1, le=6),
    predicates: str | None = Query(
        None, description="CSV predicate filter; absent = dependency defaults."
    ),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    mgr = _graph_manager()
    node_id = _resolve_ref(mgr, node)
    return {
        "node": node_id,
        "nodes": mgr.impact(
            node_id,
            max_depth=max_depth,
            predicates=_parse_predicates(predicates),
            limit=limit,
        ),
    }


@router.get(
    "/cochange",
    summary="Files that historically change with a file",
    description="Computed from currently-valid git `modifies` edges (Plan C "
    "view; needs git_indexing). Weight = number of shared commits. 503 when "
    "graph indexing is disabled.",
)
async def cochange(
    node: str = Query(..., min_length=1),
    min_shared: int = Query(2, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    mgr = _graph_manager()
    node_id = _resolve_ref(mgr, node)
    return {
        "node": node_id,
        "files": mgr.co_changed_files(node_id, min_shared=min_shared, limit=limit),
    }

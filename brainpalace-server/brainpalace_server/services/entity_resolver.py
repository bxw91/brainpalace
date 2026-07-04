"""Plan B — deterministic cross-domain entity resolution (no LLM).

Maps a doc/session entity mention onto the canonical code node it names, when
that node already exists in the graph — else the mention stays its own domain
node. Exact tiers only (never a wrong link):

T1  path mention        -> absolute POSIX File id (rel/abs join vs project root)
T2  path:fqname mention -> absolute ``path:fqname`` symbol id
T3  identifier mention  -> UNIQUE exact display-name match among code nodes

Per-endpoint domains (Plan 4): a linked endpoint is written with domain
``code`` so the code node never flips into ``doc``/``session`` (and never
enters those domains' orphan sweeps). Resolution is best-effort by contract:
a missing store method or a store error degrades to "no link", never raises
out of a write path.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from brainpalace_server.services.session_linker import _looks_like_path

logger = logging.getLogger(__name__)

# Identifier-ish mention: letters/digits/underscore/dots, at least 3 chars —
# free text (spaces) and one-letter names never reach the exact-name tier.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{2,}$")

# Session-derived endpoint types that are never code references
# (services/session_triplet_types.py); File and untyped stay eligible.
_NEVER_CODE_TYPES = {"Decision", "Error", "Session", "Tool", "Task"}


@dataclass(frozen=True)
class ResolvedEntity:
    id: str  # canonical node id: absolute POSIX path or ``path:fqname``
    name: str  # short display name (basename / symbol short name)
    label: str  # node label, e.g. File / Function / Class


def _abs_posix(project_root: str, mention: str) -> str | None:
    """Absolute POSIX path for a path mention inside the project root."""
    root = os.path.normpath(project_root)
    absp = (
        os.path.normpath(mention)
        if os.path.isabs(mention)
        else os.path.normpath(os.path.join(root, mention))
    )
    try:
        rel = os.path.relpath(absp, root)
    except ValueError:  # different drive on Windows
        return None
    if rel.startswith(".."):  # outside the project root — never guess
        return None
    return absp.replace(os.sep, "/")


def _split_fqname(mention: str) -> tuple[str, str] | None:
    """Split a ``path.py:fq.name`` mention; None when not that shape."""
    if ":" not in mention:
        return None
    path, _, fq = mention.rpartition(":")
    if not path or not fq or "/" in fq or " " in fq or not _looks_like_path(path):
        return None
    return path, fq


def _get_node(graph: Any, node_id: str) -> dict[str, Any] | None:
    fn = getattr(graph, "get_node", None)
    if fn is None:
        return None
    try:
        node = fn(node_id)
    except Exception as exc:  # noqa: BLE001 — resolution is best-effort
        logger.debug("entity_resolver.get_node failed: %s", exc)
        return None
    # Never a wrong link: T1/T2 accept only code nodes, mirroring T3's
    # ``domains=["code"]`` — a doc/session node happening to share this id
    # (e.g. an unresolved doc mention keyed by the same abs path) must not
    # be returned as a resolved code entity.
    if node is not None and node.get("domain") != "code":
        return None
    return node  # type: ignore[no-any-return]


def _exact_name(graph: Any, name: str) -> list[dict[str, Any]]:
    fn = getattr(graph, "nodes_by_exact_name", None)
    if fn is None:
        return []
    try:
        return list(fn(name, domains=["code"], limit=2))
    except Exception as exc:  # noqa: BLE001 — resolution is best-effort
        logger.debug("entity_resolver.nodes_by_exact_name failed: %s", exc)
        return []


def _entity(node: dict[str, Any]) -> ResolvedEntity:
    return ResolvedEntity(
        id=str(node["id"]),
        name=str(node.get("name") or node["id"]),
        label=str(node.get("label") or "Entity"),
    )


def resolve_entity(
    mention: str,
    entity_type: str | None,
    project_root: str,
    graph: Any,
) -> ResolvedEntity | None:
    """Resolve ``mention`` to an existing canonical code node, or None.

    ``graph`` is duck-typed (``get_node`` + ``nodes_by_exact_name``) — the
    GraphStoreManager satisfies both; fakes/simple backends degrade to None.
    """
    mention = (mention or "").strip()
    if not mention or entity_type in _NEVER_CODE_TYPES:
        return None

    if project_root:
        # T2 — path:fqname symbol mention.
        split = _split_fqname(mention)
        if split is not None:
            absp = _abs_posix(project_root, split[0])
            if absp:
                node = _get_node(graph, f"{absp}:{split[1]}")
                if node:
                    return _entity(node)
        # T1 — path mention.
        if _looks_like_path(mention):
            absp = _abs_posix(project_root, mention)
            if absp:
                node = _get_node(graph, absp)
                if node:
                    return _entity(node)

    # T3 — unique exact display-name match among code nodes. Path-like
    # mentions may retry here: a bare basename ('auth.py') misses T1 when the
    # file is not at the guessed location, but File display names ARE
    # basenames, so a unique basename still links.
    if _IDENTIFIER_RE.match(mention) or _looks_like_path(mention):
        rows = _exact_name(graph, mention)
        if len(rows) == 1:
            return _entity(rows[0])
    return None


def link_kwargs(
    subject: str,
    obj: str,
    subject_type: str | None,
    object_type: str | None,
    project_root: str,
    graph: Any,
) -> dict[str, Any]:
    """Extra ``add_triplet`` kwargs linking resolvable endpoints to code nodes.

    Empty dict when nothing resolves — merging it leaves the call site's
    existing behavior byte-identical in that case.
    """
    out: dict[str, Any] = {}
    s = resolve_entity(subject, subject_type, project_root, graph)
    o = resolve_entity(obj, object_type, project_root, graph)
    if s is not None:
        out.update(
            subject_id=s.id,
            subject_name=s.name,
            subject_type=s.label,
            subject_domain="code",
        )
    if o is not None:
        out.update(
            object_id=o.id,
            object_name=o.name,
            object_type=o.label,
            object_domain="code",
        )
    if out:
        out["edge_properties"] = {"resolved": True}
    return out

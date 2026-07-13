"""Pure prefix-swap transforms for rehome (spec A3/A5/A6/A14/D6).

Every function is side-effect-free: it takes an in-memory record (or a list of
strings) plus ``old_root``/``new_root`` and returns the migrated value. The
rehome orchestrator (Plan 04) reads rows from the stores, applies these
transforms, and writes them back through the stores' own primitives. Nothing
here touches the filesystem or a database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from brainpalace_server.rehome.detect import prefix_swap
from brainpalace_server.services.folder_manager import FolderRecord
from brainpalace_server.services.manifest_tracker import FolderManifest
from brainpalace_server.storage.reference_catalog_store import ReferenceEntry, ref_id


def swap_exclude_patterns(
    patterns: list[str], old_root: str, new_root: str
) -> list[str]:
    """Prefix-swap absolute exclude entries under ``old_root`` (D6).

    Globs (``**/node_modules/**``, ``*.log``) and absolutes outside ``old_root``
    do not start with ``old_root`` and are returned verbatim by ``prefix_swap``.
    """
    return [prefix_swap(p, old_root, new_root) for p in patterns]


def rehome_folder_record(
    record: FolderRecord, old_root: str, new_root: str
) -> FolderRecord:
    """Return a copy of ``record`` with ``folder_path`` prefix-swapped (A6/D2).

    Only ``folder_path`` is a path field on ``FolderRecord`` (the
    ``injector_script``/``folder_metadata_file`` paths live on job records — A11,
    Plan 04). ``chunk_ids`` are opaque and carried through unchanged. An
    external record (path outside ``old_root``) is returned unchanged by
    ``prefix_swap``.
    """
    return replace(
        record, folder_path=prefix_swap(record.folder_path, old_root, new_root)
    )


def rekey_manifest(
    manifest: FolderManifest, old_root: str, new_root: str
) -> FolderManifest:
    """Return a new manifest with ``folder_path`` and every file **key**
    prefix-swapped (A3/D2). ``FileRecord`` values — checksum, mtime, and the
    opaque ``chunk_ids`` — are carried through unchanged. Pure: the input is
    not mutated; the orchestrator persists under ``sha256(new_folder_path)`` and
    deletes the old manifest file.
    """
    return FolderManifest(
        folder_path=prefix_swap(manifest.folder_path, old_root, new_root),
        files={
            prefix_swap(fp, old_root, new_root): rec
            for fp, rec in manifest.files.items()
        },
    )


def rehome_reference_entry(
    entry: ReferenceEntry, old_root: str, new_root: str
) -> ReferenceEntry:
    """Return a copy of ``entry`` with ``source``/``pointer``/``source_id``
    prefix-swapped and ``id`` recomputed via ``ref_id`` (A14/D2).

    Out-of-root (e.g. virtual/URL) pointers fail the prefix test, so every field
    — including the recomputed ``id`` — is identical to the input. The PK change
    means the orchestrator persists this as insert-new + delete-old (Plan 04).
    """
    new_source = prefix_swap(entry.source, old_root, new_root)
    new_pointer = prefix_swap(entry.pointer, old_root, new_root)
    new_source_id = prefix_swap(entry.source_id, old_root, new_root)
    return entry.model_copy(
        update={
            "source": new_source,
            "pointer": new_pointer,
            "source_id": new_source_id,
            "id": ref_id(new_pointer, new_source),
        }
    )


# --- graph (A5): posix-space node-id + edge-PK migration -------------------

_SEP = "\x1f"  # MUST match storage.sqlite_graph_store._SEP (parity-tested)


def _edge_id(source_id: str, label: str, target_id: str) -> str:
    """Replica of ``sqlite_graph_store._edge_id`` — kept here so ``rehome`` stays
    ``llama_index``-free. ``test_swap_edge_id_matches_store_edge_id`` binds them."""
    return f"{source_id}{_SEP}{label}{_SEP}{target_id}"


def _posix(p: str) -> str:
    return p.replace("\\", "/")


@dataclass
class SwappedNode:
    id: str
    properties: dict[str, object]


@dataclass
class SwappedEdge:
    id: str
    source_id: str
    target_id: str
    source_file: str | None


def rehome_graph_node(
    node_id: str, properties: dict[str, object], old_root: str, new_root: str
) -> SwappedNode:
    """Prefix-swap a graph node's id (PK) and every path-valued string property
    (A5). Runs in posix space — graph ids are posix-normalized paths (File) or
    ``file:fqname`` (symbol). Non-path property values fail the D2 prefix test
    and are returned verbatim; non-string values are carried through untouched.
    """
    old_p, new_p = _posix(old_root), _posix(new_root)
    new_id = prefix_swap(_posix(node_id), old_p, new_p)
    new_props = {
        k: (prefix_swap(_posix(v), old_p, new_p) if isinstance(v, str) else v)
        for k, v in properties.items()
    }
    return SwappedNode(id=new_id, properties=new_props)


def rehome_graph_edge(
    source_id: str,
    target_id: str,
    label: str,
    source_file: str | None,
    old_root: str,
    new_root: str,
) -> SwappedEdge:
    """Prefix-swap an edge's endpoints (FK to node ids) and ``source_file``, then
    RECOMPUTE the edge id from the swapped triple (A5). Never string-replace the
    id — ``label`` sits between two path components and ``_SEP`` collisions make
    in-place replace unsafe. Endpoints not under ``old_root`` are left verbatim,
    which keeps FK integrity because node ids swap by the same rule.
    """
    old_p, new_p = _posix(old_root), _posix(new_root)
    new_source = prefix_swap(_posix(source_id), old_p, new_p)
    new_target = prefix_swap(_posix(target_id), old_p, new_p)
    new_source_file = (
        prefix_swap(_posix(source_file), old_p, new_p)
        if source_file is not None
        else None
    )
    return SwappedEdge(
        id=_edge_id(new_source, label, new_target),
        source_id=new_source,
        target_id=new_target,
        source_file=new_source_file,
    )


# D12 path-bearing chunk-metadata keys (confirmed via loader/chunker audit).
_CHUNK_PATH_KEYS = ("source", "file_path", "path", "page_label")


def swap_chunk_metadata(
    md: dict[str, object], old_root: str, new_root: str
) -> dict[str, object]:
    """Prefix-swap the D12 path-bearing keys of one chunk's metadata (vector +
    BM25 phases). ``page_label`` is swapped only when it holds an in-root path;
    a genuine label ("p. 4") fails the D2 prefix test and is left. Non-string or
    out-of-root values are unchanged; other keys pass through untouched.
    """
    out = dict(md)
    for key in _CHUNK_PATH_KEYS:
        v = out.get(key)
        if isinstance(v, str):
            out[key] = prefix_swap(v, old_root, new_root)
    return out


def rehome_simple_graph_json(json_path: str, old_root: str, new_root: str) -> int:
    """Prefix-swap the default ``simple`` graph store's persisted JSON in place.

    The ``SimplePropertyGraphStore`` JSON keys nodes by their (path-encoded) id and
    relations by the composite ``{source_id}_{label}_{target_id}``. Node ids /
    ``name`` / path properties and relation endpoints are prefix-swapped (D2); the
    composite relation keys + the ``triplets`` list are RECOMPUTED from the swapped
    endpoints (a leading-only swap would leave the target half of the composite key
    stale — the same trap A5 flags for sqlite edge ids). External / out-of-root
    strings fail the prefix test and are left. Written atomically, and only when
    something changed. Missing file / empty graph -> 0.
    """
    p = Path(json_path)
    if not p.exists():
        return 0
    try:
        data: Any = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0

    def _sw(v: Any) -> Any:
        return prefix_swap(v, old_root, new_root) if isinstance(v, str) else v

    changed = 0

    nodes = data.get("nodes")
    if isinstance(nodes, dict):
        new_nodes: dict[str, Any] = {}
        for nid, node in nodes.items():
            new_id = _sw(nid)
            if isinstance(node, dict):
                if isinstance(node.get("name"), str):
                    node["name"] = _sw(node["name"])
                props = node.get("properties")
                if isinstance(props, dict):
                    for k, v in props.items():
                        props[k] = _sw(v)
            if new_id != nid:
                changed += 1
            new_nodes[new_id] = node
        data["nodes"] = new_nodes

    relations = data.get("relations")
    if isinstance(relations, dict):
        new_relations: dict[str, Any] = {}
        for key, rel in relations.items():
            if isinstance(rel, dict):
                new_src = _sw(rel.get("source_id"))
                new_tgt = _sw(rel.get("target_id"))
                lbl = rel.get("label", "")
                rel["source_id"] = new_src
                rel["target_id"] = new_tgt
                props = rel.get("properties")
                if isinstance(props, dict):
                    for k, v in props.items():
                        props[k] = _sw(v)
                new_key = f"{new_src}_{lbl}_{new_tgt}"
                if new_key != key:
                    changed += 1
                new_relations[new_key] = rel
            else:
                new_relations[key] = rel
        data["relations"] = new_relations

    triplets = data.get("triplets")
    if isinstance(triplets, list):
        new_triplets = []
        for t in triplets:
            if isinstance(t, list) and len(t) == 3:
                new_triplets.append([_sw(t[0]), t[1], _sw(t[2])])
            else:
                new_triplets.append(t)
        data["triplets"] = new_triplets

    if changed:
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(p)
    return changed

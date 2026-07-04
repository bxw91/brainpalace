"""Parse dependency manifests → ``Package depends_on Package`` (§5b, exact).

One pass per manifest file (pyproject.toml — Poetry and PEP 621 — and
package.json), refreshed via the same per-file purge as code (§3).
Deterministic, no LLM, never raises.
"""

from __future__ import annotations

import json
import logging
import os
import re

import tomllib

from brainpalace_server.models.graph import GraphTriple

logger = logging.getLogger(__name__)

MANIFEST_BASENAMES = {"pyproject.toml", "package.json"}

_NAME_RE = re.compile(r"^[A-Za-z0-9@/_.-]+")


def is_manifest(file_path: str) -> bool:
    return os.path.basename(file_path.replace("\\", "/")) in MANIFEST_BASENAMES


def _pyproject_deps(source: str) -> tuple[str, list[str]]:
    data = tomllib.loads(source)
    project = data.get("project") or {}
    poetry = ((data.get("tool") or {}).get("poetry")) or {}
    name = project.get("name") or poetry.get("name") or ""
    deps: list[str] = []
    for spec in project.get("dependencies") or []:  # PEP 621: "requests>=2.31"
        m = _NAME_RE.match(str(spec).strip())
        if m:
            deps.append(m.group(0))
    deps.extend((poetry.get("dependencies") or {}).keys())  # Poetry table
    for group in (poetry.get("group") or {}).values():  # Poetry dev groups
        deps.extend((group.get("dependencies") or {}).keys())
    return name, [d for d in deps if d.lower() != "python"]


def _package_json_deps(source: str) -> tuple[str, list[str]]:
    data = json.loads(source)
    name = data.get("name") or ""
    deps: list[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps.extend((data.get(key) or {}).keys())
    return name, deps


def extract_manifest_deps(file_path: str, source: str) -> list[GraphTriple]:
    """``depends_on`` triples for one manifest file; [] on parse failure."""
    fp = file_path.replace("\\", "/")
    base = os.path.basename(fp)
    try:
        if base == "pyproject.toml":
            root_name, deps = _pyproject_deps(source)
        elif base == "package.json":
            root_name, deps = _package_json_deps(source)
        else:
            return []
    except (
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as exc:
        logger.debug("manifest parse failed for %s: %s", fp, exc)
        return []
    if not root_name:
        return []
    out: list[GraphTriple] = []
    seen: set[str] = set()
    for dep in deps:
        if not dep or dep == root_name or dep in seen:
            continue
        seen.add(dep)
        out.append(
            GraphTriple(
                subject=root_name,
                predicate="depends_on",
                object=dep,
                subject_id=root_name,
                object_id=dep,
                subject_name=root_name,
                object_name=dep,
                subject_type="Package",
                object_type="Package",
                source_file=fp,
            )
        )
    return out

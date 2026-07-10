#!/usr/bin/env python3
"""lint:import-boundary — the product package (brainpalace-life) touches the
engine ONLY through the seam allowlist, and never reaches into engine data
artifacts directly (SPEC decision D1 / the Packaging import-boundary rule).

Deterministic AST scan (no code execution) over product SOURCE (never tests/).
Two rules:
  R1 IMPORT  — a `brainpalace_server.*` import outside the seam allowlist, any
               `brainpalace_cli.*` import (product has no CLI dependency), or a
               dynamic `importlib.import_module('...')` / `__import__('...')`
               with a forbidden string target. `import a.b.c` and
               `from a.b import c` are both resolved to the fully-qualified
               target before matching, so package-form seam imports pass.
  R2 DATA    — a path-segment of a string literal that EXACTLY equals an engine
               data artifact (the `.brainpalace` data dir or a known `*.db`
               basename). Catches `sqlite3.connect('.brainpalace/graph_store.db')`
               / `open(...)` — the roadmap's canonical bypass, which an import
               scan cannot see. Matching is segment-anchored (splitting on path
               separators) so `.brainpalace_life/` or `old_records.db` do NOT trip,
               and DOCSTRINGS are excluded so boundary prose is not self-flagged.

Run from repo root:  python scripts/check_import_boundary.py
See docs/superpowers/specs/2026-07-06-phase8-life-scaffold-import-gate-SPEC.md.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "brainpalace-life" / "brainpalace_life"

ENGINE = "brainpalace_server"
CLI = "brainpalace_cli"

# The exact engine modules the product MAY import (submodules of each are also
# allowed), with the reason. Everything else under ENGINE is denied; CLI has no
# seams at all.
ALLOWED_SEAMS: dict[str, str] = {
    "brainpalace_server.ingestion.adapter": "adapter Protocol + Emitted* models",
    "brainpalace_server.ingestion.sink": "ingest() write seam",
    "brainpalace_server.indexing.record_validation": "register_validator/score_confidence",
    "brainpalace_server.indexing.salience": "register_salience_scorer seam",
    "brainpalace_server.models.domains": "register_domain/known_domains",
    "brainpalace_server.services.query_service": "QueryService.execute_query read seam",
    "brainpalace_server.models.record": "Record DTO",
    "brainpalace_server.models.graph": "graph DTOs",
    "brainpalace_server.models.query": "QueryRequest/QueryResponse DTOs",
}

# Engine data artifacts the product must never open directly (persistence goes
# through the seams). The data dir plus every engine db basename.
ENGINE_ARTIFACTS: tuple[str, ...] = (
    ".brainpalace",
    "graph_store.db",
    "records.db",
    "embeddings.db",
    "extraction_pending.db",
    "query_log.db",
    "reference_catalog.db",
    "rules.db",
    "self.db",
    "usage_metrics.db",
)
_ENGINE_ARTIFACT_SET = frozenset(ENGINE_ARTIFACTS)
_PATH_SEP = re.compile(r"[/\\]")

_DYNAMIC_IMPORT_FUNCS = {"import_module", "__import__"}


class Violation(NamedTuple):
    file: Path
    line: int
    rule: str  # "import" | "data-access"
    detail: str


def _under(module: str, pkg: str) -> bool:
    return module == pkg or module.startswith(pkg + ".")


def _seam_for(module: str) -> str | None:
    """The seam covering `module` (exact or submodule), or None if denied."""
    for seam in ALLOWED_SEAMS:
        if module == seam or module.startswith(seam + "."):
            return seam
    return None


def _classify_import(module: str, fallback: str | None) -> str | None:
    """Return a violation detail for an imported `module`, or None if allowed.

    `fallback` is the `from`-clause base (e.g. `from a.b import c` passes
    module=`a.b.c`, fallback=`a.b`) so a seam reached via either form passes.
    """
    candidates = [module] + ([fallback] if fallback else [])
    if any(_under(c, CLI) for c in candidates):
        return f"{module} (brainpalace_cli — product has no CLI dependency)"
    if any(_under(c, ENGINE) for c in candidates):
        if _seam_for(module) or (fallback and _seam_for(fallback)):
            return None
        return module  # engine, but not a seam
    return None  # not engine/cli — fine


def _artifact_in(text: str) -> str | None:
    """The engine artifact a path-string points at, or None.

    Segment-anchored: the string is split on `/` and `\\` and a segment must
    EQUAL an artifact. So `.brainpalace/graph_store.db` trips, but the product's
    own `.brainpalace_life/` or `old_records.db` (and plain prose that merely
    contains the substring) do not.
    """
    for seg in _PATH_SEP.split(text):
        if seg in _ENGINE_ARTIFACT_SET:
            return seg
    return None


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """Ids of the Constant nodes that are module/class/function docstrings.

    Docstrings are boundary *prose* (e.g. "never open `.brainpalace/`"), not data
    access — excluding them keeps the gate from flagging its own documentation.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(body, list)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def _scan_tree(tree: ast.AST, file: Path) -> list[Violation]:
    out: list[Violation] = []
    docstring_ids = _docstring_constant_ids(tree)
    for node in ast.walk(tree):
        # R1a: static imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                detail = _classify_import(alias.name, None)
                if detail:
                    out.append(Violation(file, node.lineno, "import", detail))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # level>0 = relative, never engine
                for alias in node.names:
                    full = f"{node.module}.{alias.name}"
                    detail = _classify_import(full, node.module)
                    if detail:
                        out.append(Violation(file, node.lineno, "import", detail))
        # R1b: dynamic imports with a string-literal target
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = (
                fn.attr
                if isinstance(fn, ast.Attribute)
                else (fn.id if isinstance(fn, ast.Name) else None)
            )
            if fname in _DYNAMIC_IMPORT_FUNCS and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    detail = _classify_import(arg.value, None)
                    if detail:
                        out.append(
                            Violation(file, node.lineno, "import", f"dynamic {detail}")
                        )
        # R2: engine data-artifact string literals (docstrings are prose, skip)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ):
            art = _artifact_in(node.value)
            if art:
                out.append(
                    Violation(
                        file,
                        node.lineno,
                        "data-access",
                        f"string {node.value!r} references engine artifact '{art}'",
                    )
                )
    return out


def find_violations(root: Path) -> list[Violation]:
    """Every boundary violation under `root` (product source), sorted stably.

    Raises nothing on a syntax error — records it as a data/parse violation so
    the gate fails cleanly instead of crashing with a traceback.
    """
    out: list[Violation] = []
    for py in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:
            out.append(Violation(py, exc.lineno or 0, "parse-error", str(exc.msg)))
            continue
        out.extend(_scan_tree(tree, py))
    return sorted(out, key=lambda v: (str(v.file), v.line, v.rule, v.detail))


def verify_seams() -> list[str]:
    """Every ALLOWED_SEAMS module that no longer imports from the live engine.

    The allowlist is otherwise a static string list the scanner never checks
    against the real engine (doc-vs-doc). Importing each seam catches drift —
    a renamed/moved seam would leave the gate green while product code breaks.
    Requires the engine (brainpalace-rag) installed in the running interpreter.
    """
    broken: list[str] = []
    for seam in ALLOWED_SEAMS:
        try:
            importlib.import_module(seam)
        except Exception as exc:  # ImportError, or a seam module that now errors
            broken.append(f"{seam}: {type(exc).__name__}: {exc}")
    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description="Product→engine import-boundary gate.")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Product source dir to scan (default: brainpalace_life/).",
    )
    parser.add_argument(
        "--verify-seams",
        action="store_true",
        help="Import every ALLOWED_SEAMS module against the live engine and fail "
        "on drift (requires brainpalace-server installed; run under its venv).",
    )
    args = parser.parse_args()
    root: Path = args.root

    if args.verify_seams:
        broken = verify_seams()
        if broken:
            print(
                "import-boundary: SEAM DRIFT — allowlisted engine modules no "
                "longer import:\n",
                file=sys.stderr,
            )
            for line in broken:
                print(f"  {line}", file=sys.stderr)
            print(
                "\nThe engine moved/renamed a seam. Update ALLOWED_SEAMS in "
                "scripts/check_import_boundary.py to the new path.",
                file=sys.stderr,
            )
            return 1
        print(f"import-boundary: OK — all {len(ALLOWED_SEAMS)} seams import live.")
        return 0

    if not root.exists():
        print(f"import-boundary: root does not exist: {root}", file=sys.stderr)
        return 1

    violations = find_violations(root)
    if not violations:
        print(f"import-boundary: OK — {root.name}/ stays within the engine seams.")
        return 0

    print("import-boundary: FORBIDDEN engine access in product source:\n")
    for v in violations:
        rel = v.file.relative_to(REPO) if v.file.is_relative_to(REPO) else v.file
        print(f"  {rel}:{v.line}  [{v.rule}]  {v.detail}")
    print(
        "\nProduct code may reach the engine ONLY through these seams:\n  "
        + "\n  ".join(ALLOWED_SEAMS)
        + "\nand must never open an engine data file directly (persist via the "
        "seams). Route through a seam, or add a new one to the engine AND to "
        "ALLOWED_SEAMS in scripts/check_import_boundary.py with a reason."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

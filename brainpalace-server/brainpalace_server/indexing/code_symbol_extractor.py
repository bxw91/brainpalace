"""Complete per-file Python symbol extraction for the code graph.

Parses a whole Python file with stdlib `ast` and emits one node per
class/function/method — independent of chunk boundaries — with canonical
`file:fqname` identity and short display names (Plan 1), a positioned symbol
table and exact intra-file `calls` edges (Plan 2), and (Plan 3) precise kinds
(Enum/Interface), the File node + Folder chain, `decorated_by` / `handled_by`
triples, unresolved import specs, and annotation reference sites for LSP.
Deterministic; never raises. Cross-file callees/targets are NOT guessed —
they are left for the import resolver and LSP.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from brainpalace_server.models.graph import GraphTriple, symbol_id

logger = logging.getLogger(__name__)

_ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}
_HTTP_METHODS = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "head",
    "options",
    "websocket",
}
# Builtin/typing names whose LSP definition is typeshed noise, not repo code.
_SKIP_REF_NAMES = {
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "bytearray",
    "complex",
    "list",
    "dict",
    "set",
    "frozenset",
    "tuple",
    "type",
    "object",
    "None",
    "Any",
    "Optional",
    "Union",
    "Callable",
    "Iterable",
    "Iterator",
    "Sequence",
    "Mapping",
    "MutableMapping",
    "Self",
    "ClassVar",
    "Annotated",
    "Literal",
    "TypeVar",
    "Generic",
}


@dataclass
class SymbolDef:
    """One defined symbol with the position needed to seed LSP queries."""

    symbol_id: str
    fqname: str
    short: str
    kind: str  # Function | Method | Class | Enum | Interface
    language: str
    file_path: str
    line: int  # 0-based, on the name token
    character: int  # column of the name token


@dataclass
class ImportSpec:
    """One import statement, unresolved (resolution needs the filesystem)."""

    module: str  # dotted module ("" for `from . import x`)
    level: int  # relative-import level; 0 = absolute
    names: list[str]  # from-import names ([] for plain `import a.b`)


@dataclass
class RefSite:
    """A non-call type-use site (annotation) to resolve via LSP definition."""

    file_path: str
    caller_id: str  # enclosing symbol id
    name: str  # dotted source text of the annotation ("pkg.Widget")
    line: int  # 0-based, at the END of the name token
    character: int
    language: str = "python"


@dataclass
class FileSymbols:
    triples: list[GraphTriple] = field(default_factory=list)
    symbols: list[SymbolDef] = field(default_factory=list)
    imports: list[ImportSpec] = field(default_factory=list)
    ref_sites: list[RefSite] = field(default_factory=list)


def _module_name(file_path: str) -> str:
    return file_path.replace("\\", "/")


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _name_col(node: ast.AST) -> int:
    """Column where the symbol name begins (after the def/class keyword)."""
    base = getattr(node, "col_offset", 0)
    if isinstance(node, ast.ClassDef):
        return base + len("class ")
    if isinstance(node, ast.AsyncFunctionDef):
        return base + len("async def ")
    return base + len("def ")


def _dotted(expr: ast.AST) -> str | None:
    """Dotted source text of a Name/Attribute chain, or None."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return f"{base}.{expr.attr}" if base else None
    return None


def _class_kind(node: ast.ClassDef) -> str:
    """Precise schema kind for a class: Enum / Interface / Class."""
    for base in node.bases:
        name = (
            base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
        )
        if name in _ENUM_BASES:
            return "Enum"
        if name == "Protocol":
            return "Interface"
    return "Class"


def _collect_type_names(expr: ast.AST) -> Iterator[ast.expr]:
    """Yield the outermost Name/Attribute nodes in an annotation expression."""
    if isinstance(expr, (ast.Name, ast.Attribute)):
        yield expr
        return
    for child in ast.iter_child_nodes(expr):
        yield from _collect_type_names(child)


def extract_python_symbols(
    file_path: str, source: str, root: str | None = None
) -> FileSymbols:
    """Return typed containment/defined_in/calls/decorator triplets, the
    File node + Folder chain (when ``root`` is given), a positioned symbol
    table, unresolved import specs, and annotation reference sites."""
    module = _module_name(file_path)
    file_display = _basename(module)
    out = FileSymbols()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out

    # Folder chain (§1/§2): derived purely from the path — deterministic, free.
    if root:
        root_norm = root.replace("\\", "/").rstrip("/")
        if module.startswith(root_norm + "/"):
            rel_parts = module[len(root_norm) + 1 :].split("/")
            parent = root_norm
            parent_name = _basename(root_norm) or root_norm
            for part in rel_parts[:-1]:
                child = f"{parent}/{part}"
                out.triples.append(
                    GraphTriple(
                        subject=parent_name,
                        predicate="contains",
                        object=part,
                        subject_id=parent,
                        object_id=child,
                        subject_name=parent_name,
                        object_name=part,
                        subject_type="Folder",
                        object_type="Folder",
                        source_file=None,  # shared chain edge — swept, not purged
                    )
                )
                parent, parent_name = child, part
            out.triples.append(
                GraphTriple(
                    subject=parent_name,
                    predicate="contains",
                    object=file_display,
                    subject_id=parent,
                    object_id=module,
                    subject_name=parent_name,
                    object_name=file_display,
                    subject_type="Folder",
                    object_type="File",
                    source_file=module,  # per-file provenance — purged with it
                )
            )

    # Import specs (§2b): collected here, resolved against the filesystem by
    # the caller (indexing/import_resolver.py) — the extractor stays pure.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.imports.append(ImportSpec(module=alias.name, level=0, names=[]))
        elif isinstance(node, ast.ImportFrom):
            out.imports.append(
                ImportSpec(
                    module=node.module or "",
                    level=node.level or 0,
                    names=[a.name for a in node.names],
                )
            )

    # id -> (short, kind) for typed, named call edges
    id_short: dict[str, str] = {}
    id_kind: dict[str, str] = {}
    # callee resolution maps
    top_funcs: dict[str, str] = {}  # top-level function short -> id
    class_methods: dict[str, dict[str, str]] = {}  # class short -> {method -> id}
    # node -> (id, fqname, class_short_or_None) for the calls pass
    node_ctx: dict[ast.AST, tuple[str, str, str | None]] = {}

    def_node = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    class_kinds = ("Class", "Enum", "Interface")

    def emit_contains(
        parent_id: str,
        parent_name: str,
        parent_type: str,
        cid: str,
        child_short: str,
        child_type: str,
    ) -> None:
        out.triples.append(
            GraphTriple(
                subject=parent_name,
                predicate="contains",
                object=child_short,
                subject_id=parent_id,
                object_id=cid,
                subject_name=parent_name,
                object_name=child_short,
                subject_type=parent_type,
                object_type=child_type,
                source_file=module,
            )
        )
        out.triples.append(
            GraphTriple(
                subject=child_short,
                predicate="defined_in",
                object=file_display,
                subject_id=cid,
                object_id=module,
                subject_name=child_short,
                object_name=file_display,
                subject_type=child_type,
                object_type="File",
                source_file=module,
            )
        )

    def emit_decorators(child: ast.AST, cid: str, short: str, ctype: str) -> None:
        for dec in getattr(child, "decorator_list", []):
            target = dec.func if isinstance(dec, ast.Call) else dec
            dotted = _dotted(target)
            if dotted:
                out.triples.append(
                    GraphTriple(
                        subject=short,
                        predicate="decorated_by",
                        object=dotted,
                        subject_id=cid,
                        object_id=f"decorator:{dotted}",
                        subject_name=short,
                        object_name=dotted,
                        subject_type=ctype,
                        object_type="Decorator",
                        source_file=module,
                    )
                )
            # Web-route decorator → Endpoint handled_by Function (§5b).
            if (
                not isinstance(child, ast.ClassDef)
                and isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr.lower() in _HTTP_METHODS
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                ep = f"{dec.func.attr.upper()} {dec.args[0].value}"
                out.triples.append(
                    GraphTriple(
                        subject=ep,
                        predicate="handled_by",
                        object=short,
                        subject_id=f"endpoint:{ep}",
                        object_id=cid,
                        subject_name=ep,
                        object_name=short,
                        subject_type="Endpoint",
                        object_type=ctype,
                        source_file=module,
                    )
                )

    def emit_ref_sites(fn: ast.FunctionDef | ast.AsyncFunctionDef, cid: str) -> None:
        args = fn.args
        anns = [
            a.annotation
            for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            if a.annotation is not None
        ]
        for extra in (args.vararg, args.kwarg):
            if extra is not None and extra.annotation is not None:
                anns.append(extra.annotation)
        if fn.returns is not None:
            anns.append(fn.returns)
        for ann in anns:
            for node in _collect_type_names(ann):
                dotted = _dotted(node)
                if not dotted or dotted.rsplit(".", 1)[-1] in _SKIP_REF_NAMES:
                    continue
                end_line = node.end_lineno or node.lineno
                end_col = (
                    node.end_col_offset
                    if node.end_col_offset is not None
                    else node.col_offset + 1
                )
                out.ref_sites.append(
                    RefSite(
                        file_path=module,
                        caller_id=cid,
                        name=dotted,
                        line=end_line - 1,
                        character=max(0, end_col - 1),
                    )
                )

    # PASS 1: structure + symbol table + decorators + ref sites
    def walk_struct(
        node: ast.AST,
        prefix: str,
        parent_id: str,
        parent_name: str,
        parent_type: str,
        class_short: str | None,
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, def_node):
                short = child.name
                fq = f"{prefix}{short}" if prefix else short
                cid = symbol_id(module, fq)
                if isinstance(child, ast.ClassDef):
                    ctype = _class_kind(child)
                elif parent_type in class_kinds:
                    ctype = "Method"
                else:
                    ctype = "Function"
                emit_contains(parent_id, parent_name, parent_type, cid, short, ctype)
                emit_decorators(child, cid, short, ctype)
                if not isinstance(child, ast.ClassDef):
                    emit_ref_sites(child, cid)
                id_short[cid] = short
                id_kind[cid] = ctype
                out.symbols.append(
                    SymbolDef(
                        symbol_id=cid,
                        fqname=fq,
                        short=short,
                        kind=ctype,
                        language="python",
                        file_path=module,
                        line=max(0, getattr(child, "lineno", 1) - 1),
                        character=_name_col(child),
                    )
                )
                if isinstance(child, ast.ClassDef):
                    class_methods.setdefault(short, {})
                elif parent_type == "File":
                    top_funcs[short] = cid
                elif parent_type in class_kinds and class_short is not None:
                    class_methods.setdefault(class_short, {})[short] = cid
                node_ctx[child] = (
                    cid,
                    fq,
                    short if isinstance(child, ast.ClassDef) else class_short,
                )
                walk_struct(
                    child,
                    f"{fq}.",
                    cid,
                    short,
                    ctype,
                    short if isinstance(child, ast.ClassDef) else class_short,
                )
            else:
                # Non-def compound statements (if/try/with/for/…) don't open a
                # symbol scope, but a def can be nested inside one. Descend with
                # the SAME context so those defs are registered in node_ctx —
                # pass 2 (walk_calls) traverses every child and would otherwise
                # KeyError on an unregistered def.
                walk_struct(
                    child, prefix, parent_id, parent_name, parent_type, class_short
                )

    walk_struct(tree, "", module, file_display, "File", None)

    # PASS 2: intra-file calls
    def resolve(func_expr: ast.AST, class_short: str | None) -> str | None:
        if isinstance(func_expr, ast.Name):
            return top_funcs.get(func_expr.id)
        if (
            isinstance(func_expr, ast.Attribute)
            and isinstance(func_expr.value, ast.Name)
            and func_expr.value.id == "self"
            and class_short is not None
        ):
            return class_methods.get(class_short, {}).get(func_expr.attr)
        return None

    def emit_call(caller_id: str, callee_id: str) -> None:
        if caller_id == callee_id:  # drop self-loops
            return
        out.triples.append(
            GraphTriple(
                subject=id_short.get(caller_id, caller_id),
                predicate="calls",
                object=id_short.get(callee_id, callee_id),
                subject_id=caller_id,
                object_id=callee_id,
                subject_name=id_short.get(caller_id, caller_id),
                object_name=id_short.get(callee_id, callee_id),
                subject_type=id_kind.get(caller_id),
                object_type=id_kind.get(callee_id),
                source_file=module,
            )
        )

    def walk_calls(
        node: ast.AST, caller_id: str | None, class_short: str | None
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, def_node):
                ctx = node_ctx.get(child)
                if ctx is None:
                    # Defensive: an unregistered def (should not happen now that
                    # pass 1 descends into non-def blocks) — recurse without a
                    # new caller context rather than crash the whole build.
                    walk_calls(child, caller_id, class_short)
                    continue
                cid, _fq, cls = ctx
                if isinstance(child, ast.ClassDef):
                    # a class body is not a caller; keep the enclosing caller_id
                    walk_calls(child, caller_id, cls)
                else:
                    walk_calls(child, cid, cls)
                continue
            if isinstance(child, ast.Call) and caller_id is not None:
                target = resolve(child.func, class_short)
                if target:
                    emit_call(caller_id, target)
            walk_calls(child, caller_id, class_short)

    walk_calls(tree, None, None)
    return out


def extract_python_file(file_path: str, source: str) -> list[GraphTriple]:
    """Back-compat: flat triple list, no Folder chain (no root known)."""
    return extract_python_symbols(file_path, source).triples

# brainpalace-cli/brainpalace_cli/doc_sync/introspect.py
"""Build an InterfaceSnapshot from the LIVE Click group. No app import, no DB,
no network. The dump-interface command (Task 10) wraps this and is pinned to the
repo env so a stale global binary can never introspect the wrong code."""

from __future__ import annotations

import json
import os
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from pydantic import BaseModel

from brainpalace_cli.doc_sync import SCHEMA_VERSION
from brainpalace_cli.doc_sync.facts import (
    CommandFact,
    FlagFact,
    InterfaceSnapshot,
    canon_flag_name,
)


def _normalize_default(value: object) -> object:
    """Coerce a Click option default into a JSON-/contract-safe value.

    Click 8.3+ uses an internal ``Sentinel.UNSET`` enum member to mark "no
    default given"; it is not JSON-serializable and is not a real contract
    value. Detect it structurally (the symbol is private) and treat it — like
    any other unset default — as ``None``.
    """
    if type(value).__name__ == "Sentinel":
        return None
    return value


def _resolve_flag_default(p: click.Option) -> object:
    """The default a USER actually gets, not the raw Click attribute.

    A ``flag_value`` pair (``--project``/``--global`` writing one ``scope``
    dest) marks its default member with ``default=True``. Click resolves that
    to the member's ``flag_value`` — ``scope`` defaults to ``"project"``, never
    to literal ``True``. Reading ``p.default`` verbatim publishes a contract
    fact no invocation can produce.

    Deliberately narrow: only the non-bool ``flag_value`` case is rewritten. A
    plain ``is_flag`` boolean keeps its ``True`` (its ``flag_value`` IS
    ``True``), and we never call ``get_default()``, which would resolve envvars
    and callables and make this contract vary by environment.
    """
    if p.default is True and not p.is_bool_flag and p.flag_value not in (True, None):
        return p.flag_value
    return p.default


def _extract_modes(group: click.Group) -> list[str]:
    """Mode list = the `--mode` Choice on the `query` command (definition order)."""
    query = group.commands.get("query")
    if query is None:
        return []
    for p in query.params:
        if isinstance(p, click.Option) and "--mode" in p.opts:
            choices = getattr(p.type, "choices", None)
            if choices:
                return list(choices)
    return []


def _flag_facts(cmd: click.Command) -> list[FlagFact]:
    out: list[FlagFact] = []
    for p in cmd.params:
        if not isinstance(p, click.Option):
            continue  # arguments handled separately if needed later
        name = canon_flag_name(list(p.opts))
        ftype = "bool" if p.is_flag else getattr(p.type, "name", "text")
        out.append(
            FlagFact(
                name=name,
                type=ftype,
                default=_normalize_default(_resolve_flag_default(p)),
                required=bool(p.required),
                description=(p.help or ""),
            )
        )
    return out


def snapshot_from_group(group: click.Group, source_version: str) -> InterfaceSnapshot:
    commands: list[CommandFact] = []
    for name, cmd in group.commands.items():
        commands.append(
            CommandFact(
                name=name,
                hidden=bool(getattr(cmd, "hidden", False)),
                deprecated=bool(getattr(cmd, "deprecated", False)),
                flags=_flag_facts(cmd),
            )
        )
    return InterfaceSnapshot(
        schema_version=SCHEMA_VERSION,
        source_version=source_version,
        commands=commands,
        modes=_extract_modes(group),
    )


def _unwrap_model(annotation: object) -> type[BaseModel] | None:
    """Return the pydantic BaseModel a config field nests, if any.

    Handles bare ``Model`` and ``Optional[Model]`` / ``Model | None`` annotations
    (the loaders mark nested sub-sections like ``storage.postgres`` optional)."""
    import typing

    from pydantic import BaseModel

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return None


def _model_leaf_dotpaths(prefix: str, model: type[BaseModel]) -> set[str]:
    """Recursively collect leaf config dotpaths under ``prefix`` for a pydantic
    model, descending into nested BaseModel sub-sections (and keeping the bare
    sub-section dotpath too, since docs reference it as a section)."""
    out: set[str] = set()
    for fname, field in model.model_fields.items():
        dotted = f"{prefix}.{fname}"
        out.add(dotted)
        sub = _unwrap_model(field.annotation)
        if sub is not None:
            out |= _model_leaf_dotpaths(dotted, sub)
    return out


def _server_config_dotpaths() -> set[str]:
    """Full schema for the sections backed by server pydantic models.

    The CLI ``config_schema`` is only a subset/wizard validator — it omits fields
    the server actually accepts (e.g. ``GraphRAGConfig`` has 12 fields, the CLI
    knows 4; ``storage.postgres.*`` and ``session_indexing.archive.*`` are nested).
    The section→model mapping mirrors the server's own config loaders."""
    try:
        from brainpalace_server.config.git_config import GitIndexingConfig
        from brainpalace_server.config.indexing_config import IndexingConfig
        from brainpalace_server.config.provider_config import ProviderSettings
        from brainpalace_server.config.query_log_config import QueryLogConfig
        from brainpalace_server.config.session_config import (
            SessionExtractionConfig,
            SessionIndexingConfig,
        )
    except ImportError:
        return set()  # server not importable → CLI subset still applies

    out: set[str] = set()
    # ProviderSettings field names ARE the section names (embedding, graphrag, ...).
    for sec, field in ProviderSettings.model_fields.items():
        sub = _unwrap_model(field.annotation)
        if sub is not None:
            out |= _model_leaf_dotpaths(sec, sub)
    # Standalone section models (section keys verified against the server loaders).
    standalone: tuple[tuple[str, type[BaseModel]], ...] = (
        ("indexing", IndexingConfig),
        ("git_indexing", GitIndexingConfig),
        ("query_log", QueryLogConfig),
        ("session_indexing", SessionIndexingConfig),
        ("session_extraction", SessionExtractionConfig),
    )
    for sec, model in standalone:
        out |= _model_leaf_dotpaths(sec, model)
    return out


def config_dotpaths() -> list[str]:
    """Valid config keys as dotpaths, COMPLETE across both sources of truth.

    Union the CLI ``config_schema`` (authoritative for sections without a server
    model — api, bm25, cli, dashboard, server, project) with the server pydantic
    models (authoritative full field set for the provider/indexing/session
    sections). Bare top-level keys are included too."""
    from brainpalace_cli import config_schema as _cs

    out: set[str] = set(_cs.VALID_TOP_LEVEL_KEYS)
    for section, spec in _cs._SECTION_SCHEMA.items():
        out.add(section)
        for f in spec.get("known_fields", ()):
            out.add(f"{section}.{f}")
    # storage.postgres.* is a nested sub-section the CLI validates via its own
    # field set; expand it (mirrors the dashboard-parity schema enumeration).
    for pg in getattr(_cs, "POSTGRES_KNOWN_FIELDS", ()):
        out.add(f"storage.postgres.{pg}")
    out |= _server_config_dotpaths()
    return sorted(out)


def provider_registry() -> dict[str, dict[str, dict[str, object]]]:
    """The canonical provider registry (kind -> provider -> info). Single source of
    truth for which models / api-key env var each provider supports."""
    from brainpalace_cli.providers import descriptor

    return descriptor()


def install_dir_map() -> dict[str, dict[str, str]]:
    """runtime -> scope -> install path, from the install-agent command's map."""
    from brainpalace_cli.commands.install_agent import INSTALL_DIRS

    return {rt: dict(scopes) for rt, scopes in INSTALL_DIRS.items()}


def live_snapshot() -> InterfaceSnapshot:
    from brainpalace_cli.cli import cli  # lightweight import: Click group only

    snap = snapshot_from_group(cli, source_version=_pkg_version("brainpalace-cli"))
    snap.config_keys = config_dotpaths()
    snap.mcp_tools = mcp_tool_names()
    snap.providers = provider_registry()
    snap.install_dirs = install_dir_map()
    return snap  # endpoints stay opt-in (Task 5), not loaded here


def endpoint_paths() -> list[str]:
    """All HTTP route paths the project exposes, via plain import (lifespans are
    deferred → no connect/bind). Unions the project-server app and the
    control-plane dashboard app so docs referencing either are validated. Opt-in:
    NOT called by live_snapshot(), only by the endpoints checker / dump."""
    os.environ.setdefault("BRAINPALACE_INTROSPECT", "1")

    from brainpalace_server.api.main import app as _server_app  # routes only

    apps = [_server_app]
    # `BRAINPALACE_DOCSYNC_NO_DASHBOARD` forces the dashboard-absent path even when
    # the package is importable, so `task release:rehearse-ci` can reproduce the
    # publish CI gate (server+cli env, no dashboard) on a dev box of any Python
    # version. Otherwise the dashboard is unioned in when installed.
    if not os.environ.get("BRAINPALACE_DOCSYNC_NO_DASHBOARD"):
        try:
            from brainpalace_dashboard.app import create_app as _dash_create_app

            apps.append(
                _dash_create_app()
            )  # side-effect-free factory (lifespan deferred)
        except ImportError:
            pass  # dashboard optional / not installed → project-server routes only

    paths: set[str] = set()
    for app in apps:
        for route in app.routes:
            p = getattr(route, "path", None)
            if isinstance(p, str) and p.startswith("/"):
                paths.add(p)
    return sorted(paths)


def mcp_tool_names() -> list[str]:
    """Return sorted list of MCP tool names from the live tool registry."""
    from brainpalace_cli.mcp_server.server import _TOOL_DESCRIPTIONS

    return sorted(_TOOL_DESCRIPTIONS)


def dump_interface_json() -> str:
    snap = live_snapshot()
    return json.dumps(
        {
            "schema_version": snap.schema_version,
            "source_version": snap.source_version,
            "commands": [
                {
                    "name": c.name,
                    "hidden": c.hidden,
                    "deprecated": c.deprecated,
                    "flags": [
                        {
                            "name": f.name,
                            "type": f.type,
                            "default": f.default,
                            "required": f.required,
                            "description": f.description,
                        }
                        for f in c.flags
                    ],
                }
                for c in snap.commands
            ],
            "modes": snap.modes,
            "config_keys": snap.config_keys,
            "mcp_tools": snap.mcp_tools,
        },
        indent=2,
        sort_keys=True,
    )

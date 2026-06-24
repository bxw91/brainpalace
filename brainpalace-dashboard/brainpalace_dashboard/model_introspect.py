"""Reflect the server's pydantic config models — the single source of truth.

The dashboard form is generated from these models so it auto-tracks config
changes: add a field to a model and it appears, change its type/default and the
control/default follow, remove it and it disappears (the parity gate enforces
each). ``ui_schema`` consumes this for the field SET + each field's widget,
default, and enum options; only presentation (labels/help/visibility) and the
handful of values the models can't express stay hand-authored there.

Why reflect the *server* models from the *dashboard* package: the dashboard
depends on ``brainpalace-cli`` which hard-depends on ``brainpalace-rag`` (the
server), so ``brainpalace_server.config.*`` is always importable wherever the
dashboard runs.

What the models cannot express (kept as small fallbacks in ``ui_schema``):
- ``storage.backend`` / ``graphrag.store_type`` / ``graphrag.doc_extractor`` are
  plain ``str`` validated by a ``field_validator``, not ``Literal``/``Enum``, so
  their options are not in the annotation — supplied via ``ENUM_FALLBACKS``.
- ``graphrag.*`` defaults to ``None`` in the model (the real default lives in
  ``settings.py``); the effective defaults are supplied via ``DEFAULT_FALLBACKS``.
- ``storage.postgres`` is a free-form ``dict`` (no nested model); its sub-fields
  come from ``config_schema.POSTGRES_*`` and are handled directly in ``ui_schema``.
"""

from __future__ import annotations

import enum
import types
from typing import Any, Literal, Union, get_args, get_origin

from brainpalace_server.config.bm25_config import BM25Config
from brainpalace_server.config.git_config import GitIndexingConfig
from brainpalace_server.config.provider_config import (
    ComputeConfig,
    EmbeddingConfig,
    GraphRAGConfig,
    RerankerConfig,
    StorageConfig,
    SummarizationConfig,
)
from brainpalace_server.config.query_log_config import QueryLogConfig
from brainpalace_server.config.session_config import (
    SessionArchiveConfig,
    SessionExtractionConfig,
    SessionIndexingConfig,
)
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

#: section key -> pydantic model. The single source for that section's fields,
#: types, and defaults. Sections WITHOUT a model (``api`` / ``server`` /
#: ``project`` — runtime-bind & machine identity) are not here; ui_schema keeps
#: them hidden/read-only.
SECTION_MODELS: dict[str, type[BaseModel]] = {
    "embedding": EmbeddingConfig,
    "summarization": SummarizationConfig,
    "reranker": RerankerConfig,
    "storage": StorageConfig,
    "graphrag": GraphRAGConfig,
    "query_log": QueryLogConfig,
    "bm25": BM25Config,
    "git_indexing": GitIndexingConfig,
    "session_indexing": SessionIndexingConfig,
    "session_extraction": SessionExtractionConfig,
    "compute": ComputeConfig,
}

#: dotpath of a model field that is itself a nested pydantic model -> that model.
#: Rendered as its own controls (a group, or — for the archive — its own
#: section). ``storage.postgres`` is NOT here: it is a raw dict, handled from
#: config_schema in ui_schema.
NESTED_MODELS: dict[str, type[BaseModel]] = {
    "session_indexing.archive": SessionArchiveConfig,
}


def _unwrap_optional(annotation: Any) -> Any:
    """Strip ``| None`` (``Optional``) so ``str | None`` reflects like ``str``.

    Handles BOTH union spellings: ``typing.Optional[x]`` (origin
    ``typing.Union``) and PEP-604 ``x | None`` (origin ``types.UnionType``).
    """
    if get_origin(annotation) in (Union, types.UnionType):
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


def widget_and_options(annotation: Any) -> tuple[str, list[str] | None]:
    """Map a field annotation to a (widget, enum-options) pair.

    Options are returned only when the annotation itself enumerates them
    (``Literal[...]`` or an ``Enum`` subclass). Plain ``str`` fields whose
    allowed values are enforced by a validator return ``("text", None)`` — the
    caller supplies options from ``ENUM_FALLBACKS``.
    """
    ann = _unwrap_optional(annotation)
    origin = get_origin(ann)

    if origin is Literal:
        return "enum", [str(a) for a in get_args(ann)]
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return "enum", [str(m.value) for m in ann]
    if ann is bool:
        return "toggle", None
    if ann is int:
        return "int", None
    if origin in (dict, "dict") or ann is dict:
        return "dict", None
    if origin in (list, "list") or ann is list:
        return "stringlist", None
    # str, float, and everything else fall back to a free-text control.
    return "text", None


def field_default(model: type[BaseModel], name: str) -> Any:
    """Effective default for a model field as a JSON-safe scalar.

    Enum defaults collapse to their ``.value`` (models use
    ``use_enum_values=True``); ``default_factory`` (dict/list) is invoked;
    ``PydanticUndefined`` (required, no default) becomes ``None``.
    """
    f = model.model_fields[name]
    if f.default_factory is not None:
        try:
            return f.default_factory()  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001 — never break schema generation
            return None
    default = f.default
    if default is PydanticUndefined:
        return None
    if isinstance(default, enum.Enum):
        return default.value
    return default


def model_field_names(section: str) -> set[str]:
    """All field names of a section's model (the section's user-facing surface).

    Curation (hiding legacy/internal knobs) is applied by ui_schema via
    ``DASHBOARD_HIDDEN_FIELDS`` — this returns the full model surface so a newly
    added field is visible by default (and the gate forces a decision on it).
    """
    return set(SECTION_MODELS[section].model_fields.keys())


def derive_field(section: str, name: str) -> dict[str, Any]:
    """Per-field metadata derived purely from the model: widget, default, options."""
    model = SECTION_MODELS[section]
    annotation = model.model_fields[name].annotation
    widget, options = widget_and_options(annotation)
    out: dict[str, Any] = {"widget": widget, "default": field_default(model, name)}
    if options is not None:
        out["options"] = options
    return out


def nested_field(parent_dotpath: str, name: str) -> dict[str, Any]:
    """Per-field metadata for a field of a NESTED model (e.g. the archive)."""
    model = NESTED_MODELS[parent_dotpath]
    annotation = model.model_fields[name].annotation
    widget, options = widget_and_options(annotation)
    out: dict[str, Any] = {"widget": widget, "default": field_default(model, name)}
    if options is not None:
        out["options"] = options
    return out


def nested_field_names(parent_dotpath: str) -> list[str]:
    """Ordered field names of a nested model (declaration order)."""
    return list(NESTED_MODELS[parent_dotpath].model_fields.keys())

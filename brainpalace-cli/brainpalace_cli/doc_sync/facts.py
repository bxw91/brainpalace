# brainpalace-cli/brainpalace_cli/doc_sync/facts.py
"""Typed interface facts + pure normalization. The CONTRACT (name/type/default/
required) is what the checker compares; description is prose and never gated."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}
_EMPTY = {"", "-", "none", "null"}


def canon_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f"not a bool: {v!r}")


def canon_default(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    if isinstance(v, str) and v.strip().lower() in _EMPTY:
        return None
    return v


def canon_flag_name(opts: list[str]) -> str:
    """From Click option strings pick the long form, strip leading dashes."""
    longs = [o for o in opts if o.startswith("--")]
    chosen = longs[0] if longs else opts[0]
    return chosen.lstrip("-")


@dataclass(frozen=True)
class FlagFact:
    name: str
    type: str
    default: Any
    required: bool
    description: str = ""  # prose: excluded from equality

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FlagFact):
            return NotImplemented
        return (self.name, self.type, canon_default(self.default), self.required) == (
            other.name,
            other.type,
            canon_default(other.default),
            other.required,
        )

    def __hash__(self) -> int:
        # Must match __eq__: same canonicalized tuple, so equal flags hash equal.
        return hash((self.name, self.type, canon_default(self.default), self.required))


@dataclass
class CommandFact:
    name: str
    hidden: bool = False
    deprecated: bool = False
    flags: list[FlagFact] = field(default_factory=list)


@dataclass
class InterfaceSnapshot:
    schema_version: int
    source_version: str
    commands: list[CommandFact] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    mcp_tools: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    # kind -> provider -> {models, needs_base_url, default_api_key_env}
    # (from brainpalace_cli.providers.PROVIDERS — the canonical provider registry).
    providers: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    # runtime -> scope -> install path (from install_agent.INSTALL_DIRS).
    install_dirs: dict[str, dict[str, str]] = field(default_factory=dict)


class DriftKind(str, Enum):
    MISSING = "missing"  # live thing has no doc
    EXTRA = "extra"  # doc for a thing that no longer exists
    MISMATCH = "mismatch"  # contract differs
    RENAME = "rename"  # likely rename (orphan doc + new live name)
    INVALID = "invalid"  # malformed doc / markers / introspection


@dataclass
class DriftRecord:
    surface: str
    source_id: str
    doc_path: str
    kind: DriftKind
    detail: str

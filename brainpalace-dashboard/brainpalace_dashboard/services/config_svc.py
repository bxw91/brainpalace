"""ConfigService: read/validate/write config.yaml; mask secrets.

The dashboard edits the high-value provider/storage/graphrag/reranker settings
that live in ``<state_dir>/config.yaml`` (validated by ``validate_config_dict``).
Runtime bind host/port live in ``config.json`` and are managed by the lifecycle
service, not here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from brainpalace_cli.config_schema import validate_config_dict

from brainpalace_dashboard.ui_schema import build_ui_schema

MASK = "********"

# Dotpaths whose values must never leave the server in clear text.
SECRET_DOTPATHS = {
    "embedding.api_key",
    "summarization.api_key",
    "storage.postgres.password",
}


def _walk_secret(values: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-ish copy of ``values`` with secret values replaced by MASK."""
    out: dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in values.items()
    }
    for dotpath in SECRET_DOTPATHS:
        parts = dotpath.split(".")
        node: Any = out
        for p in parts[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                node = None
                break
        if isinstance(node, dict) and parts[-1] in node and node[parts[-1]]:
            node[parts[-1]] = MASK
    return out


class ConfigWriteError(Exception):
    """Raised when a batched config write fails validation (all-or-nothing)."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} config validation error(s)")


_MISSING = object()


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested config dict to ``dotpath -> leaf value``.

    Nested dicts recurse; lists/scalars are leaves compared by equality.
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _changed_dotpaths(merged: dict[str, Any], existing: dict[str, Any]) -> set[str]:
    """Leaf dotpaths whose value differs from (or is absent in) ``existing``.

    These are the fields the current save actually touches — the only fields a
    save may legitimately be blocked on.
    """
    flat_new = _flatten(merged)
    flat_old = _flatten(existing)
    return {p for p, v in flat_new.items() if flat_old.get(p, _MISSING) != v}


def _merge_secrets(new: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Replace any MASK value in ``new`` with the real value from ``existing``.

    If the field is masked but no real value exists, drop it so the mask string
    is never persisted. Non-masked values pass through (allowing a real update).
    """
    out: dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in new.items()
    }
    for dotpath in SECRET_DOTPATHS:
        parts = dotpath.split(".")
        nnode: Any = out
        enode: Any = existing
        for p in parts[:-1]:
            nnode = nnode.get(p) if isinstance(nnode, dict) else None
            enode = enode.get(p) if isinstance(enode, dict) else None
            if nnode is None:
                break
        if isinstance(nnode, dict) and nnode.get(parts[-1]) == MASK:
            real = enode.get(parts[-1]) if isinstance(enode, dict) else None
            if real is not None:
                nnode[parts[-1]] = real
            else:
                nnode.pop(parts[-1], None)
    return out


class ConfigService:
    def _config_path(self, state_dir: Path) -> Path:
        return Path(state_dir) / "config.yaml"

    def read(self, state_dir: Path) -> dict[str, Any]:
        path = self._config_path(state_dir)
        raw = yaml.safe_load(path.read_text()) if path.exists() else {}
        return _walk_secret(raw or {})

    def schema(self) -> dict[str, Any]:
        return build_ui_schema()

    def validate(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        # The dashboard is an EDITOR, not a strict linter. Real config.yaml
        # files carry legacy fields and other-tool sections the schema does not
        # model; the write path persists the merged dict verbatim, so those
        # bits survive a save. We must therefore never block a save on
        # "unknown" errors — only on genuine enum/type problems. (A strict
        # `brainpalace config validate` lint surface still reports the unknowns.)
        errs = validate_config_dict(values)
        return [
            {"field": e.field, "message": e.message, "suggestion": e.suggestion}
            for e in errs
            if not e.message.startswith(("Unknown top-level key", "Unknown key"))
        ]

    def write(self, state_dir: Path, values: dict[str, Any]) -> None:
        state_dir = Path(state_dir)
        path = self._config_path(state_dir)
        existing = yaml.safe_load(path.read_text()) if path.exists() else {}
        merged = _merge_secrets(values, existing or {})
        # Editor semantics: only block the save on validation errors in fields
        # this save actually CHANGES. A real config.yaml may already contain a
        # value the current schema rejects (a freshly-added enum value not yet
        # in the validator, a legacy field, an other-tool section). Blocking a
        # save because of a pre-existing value the user never touched makes the
        # editor unusable; such values are preserved verbatim. Genuine mistakes
        # in fields the user is editing are still caught.
        changed = _changed_dotpaths(merged, existing or {})
        errors = [e for e in self.validate(merged) if e["field"] in changed]
        if errors:
            raise ConfigWriteError(errors)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(merged, sort_keys=False))
        if path.exists():
            path.replace(path.with_suffix(".yaml.bak"))
        os.replace(tmp, path)

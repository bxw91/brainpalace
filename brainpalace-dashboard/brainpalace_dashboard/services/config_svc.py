"""ConfigService: read/validate/write config.yaml; mask secrets.

The dashboard edits the high-value provider/storage/graphrag/reranker settings
that live in ``<state_dir>/config.yaml`` (validated by ``validate_config_dict``).
Runtime bind host/port live in the ``config.yaml`` ``bind:`` section (model-backed,
auto-rendered via the registry).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from brainpalace_cli.config_schema import validate_config_dict
from brainpalace_cli.xdg_paths import get_xdg_config_dir

from brainpalace_dashboard.ui_schema import DEFAULTS, build_ui_schema

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


def _unset_dotpath(config: dict[str, Any], dotpath: str) -> bool:
    """Delete ``dotpath`` from ``config`` in place, pruning emptied parents.

    Returns True if a key was removed. Mirrors the CLI ``config_resolve``
    implementation so unset behaves identically from the dashboard and the CLI.
    """
    parts = dotpath.split(".")
    stack: list[tuple[dict[str, Any], str]] = []
    cur: Any = config
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        stack.append((cur, part))
        cur = cur[part]
    leaf = parts[-1]
    if not isinstance(cur, dict) or leaf not in cur:
        return False
    del cur[leaf]
    for parent, key in reversed(stack):
        if parent[key] == {}:
            del parent[key]
        else:
            break
    return True


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


def _mask_value(dotpath: str, value: Any) -> Any:
    """Mask a leaf value when its dotpath is a secret and it's set."""
    if dotpath in SECRET_DOTPATHS and value:
        return MASK
    return value


class ConfigService:
    def _config_path(self, state_dir: Path) -> Path:
        return Path(state_dir) / "config.yaml"

    def _global_config_path(self) -> Path:
        return Path(get_xdg_config_dir()) / "config.yaml"

    @staticmethod
    def _raw(path: Path) -> dict[str, Any]:
        """Parse a config.yaml to a dict (unmasked); {} when absent/empty."""
        loaded = yaml.safe_load(path.read_text()) if path.exists() else {}
        return loaded if isinstance(loaded, dict) else {}

    def read(self, state_dir: Path) -> dict[str, Any]:
        return _walk_secret(self._raw(self._config_path(state_dir)))

    def read_global(self) -> dict[str, Any]:
        """Read the GLOBAL XDG ``config.yaml`` (secrets masked).

        Same masking semantics as :meth:`read` — the global file IS the
        editable layer here (no provenance/effective resolution needed)."""
        return _walk_secret(self._raw(self._global_config_path()))

    def effective(self, state_dir: Path) -> dict[str, dict[str, Any]]:
        """Resolve each config key across project > global > code default.

        Returns ``{dotpath: {"value": <effective, secrets masked>,
        "source": "project"|"global"|"default", "inherited": {...}|None}}``.

        ``inherited`` is populated only when the key is set at the PROJECT layer:
        it is the ``{"value", "source"}`` the key WOULD resolve to if the project
        override were removed (unset) — i.e. the global value, else the code
        default, else ``None``. The dashboard uses it to show the live
        "if you unset this, it becomes X (from <source>)" hint next to the unset
        control. A key absent from all three layers is omitted.
        """
        project = _flatten(self._raw(self._config_path(state_dir)))
        global_ = _flatten(self._raw(self._global_config_path()))
        out: dict[str, dict[str, Any]] = {}
        for dotpath in set(project) | set(global_) | set(DEFAULTS):
            if dotpath in project:
                value, source = project[dotpath], "project"
            elif dotpath in global_:
                value, source = global_[dotpath], "global"
            else:
                value, source = DEFAULTS[dotpath], "default"
            entry: dict[str, Any] = {
                "value": _mask_value(dotpath, value),
                "source": source,
            }
            entry["inherited"] = (
                self._inherited_for(dotpath, global_) if source == "project" else None
            )
            out[dotpath] = entry
        return out

    @staticmethod
    def _inherited_for(
        dotpath: str, global_flat: dict[str, Any]
    ) -> dict[str, Any] | None:
        """What ``dotpath`` resolves to if the project override is removed."""
        if dotpath in global_flat:
            return {
                "value": _mask_value(dotpath, global_flat[dotpath]),
                "source": "global",
            }
        if dotpath in DEFAULTS:
            return {
                "value": _mask_value(dotpath, DEFAULTS[dotpath]),
                "source": "default",
            }
        return None

    def unset(self, state_dir: Path, dotpaths: list[str]) -> dict[str, Any]:
        """Remove project-level keys so they inherit from global / code default.

        Deletes each dotpath from ``<state_dir>/config.yaml`` (pruning emptied
        parent blocks), persists, and returns ``{"removed": [...], "effective":
        {dotpath: {value, source}}}`` where ``effective`` reports the NEW resolved
        value + source for each requested key after the unset. Idempotent: a key
        already absent is reported but not in ``removed``.
        """
        path = self._config_path(Path(state_dir))
        data = self._raw(path)
        removed = [dp for dp in dotpaths if _unset_dotpath(data, dp)]
        if removed:
            self._atomic_write(path, data)
        global_ = _flatten(self._raw(self._global_config_path()))
        now: dict[str, Any] = {}
        for dp in dotpaths:
            inh = self._inherited_for(dp, global_)
            now[dp] = inh or {"value": None, "source": "unset"}
        return {"removed": removed, "effective": now}

    def effective_global(self) -> dict[str, dict[str, Any]]:
        """Resolve each global config key across global-file > code default.

        The GLOBAL layer has no project override above it, so ``source`` is
        ``"global"`` (set in the file) or ``"default"`` (code default).
        ``inherited`` is the code default a key falls back to when its global
        override is removed — populated only for ``source == "global"`` keys.
        """
        global_ = _flatten(self._raw(self._global_config_path()))
        out: dict[str, dict[str, Any]] = {}
        for dotpath in set(global_) | set(DEFAULTS):
            if dotpath in global_:
                value, source = global_[dotpath], "global"
            else:
                value, source = DEFAULTS[dotpath], "default"
            entry: dict[str, Any] = {
                "value": _mask_value(dotpath, value),
                "source": source,
            }
            entry["inherited"] = (
                {
                    "value": _mask_value(dotpath, DEFAULTS[dotpath]),
                    "source": "default",
                }
                if source == "global" and dotpath in DEFAULTS
                else None
            )
            out[dotpath] = entry
        return out

    def unset_global(self, dotpaths: list[str]) -> dict[str, Any]:
        """Remove keys from the GLOBAL config.yaml so they fall back to code default.

        Mirrors :meth:`unset` for the global layer: deletes each dotpath from the
        XDG ``config.yaml`` (pruning emptied parents), persists atomically, and
        reports the NEW resolved value+source per requested key (the code default,
        or ``{"value": None, "source": "unset"}`` for a key with no default).
        """
        path = self._global_config_path()
        data = self._raw(path)
        removed = [dp for dp in dotpaths if _unset_dotpath(data, dp)]
        if removed:
            self._atomic_write(path, data)
        now: dict[str, Any] = {}
        for dp in dotpaths:
            if dp in DEFAULTS:
                now[dp] = {"value": _mask_value(dp, DEFAULTS[dp]), "source": "default"}
            else:
                now[dp] = {"value": None, "source": "unset"}
        return {"removed": removed, "effective": now}

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

    def write(
        self,
        state_dir: Path,
        values: dict[str, Any],
        unset: list[str] | tuple[str, ...] = (),
    ) -> None:
        # Project layer inherits from the global file, then the code default.
        global_flat = _flatten(self._raw(self._global_config_path()))
        self._write_to(
            self._config_path(Path(state_dir)), values, unset, inherit_from=global_flat
        )

    def write_global(
        self, values: dict[str, Any], unset: list[str] | tuple[str, ...] = ()
    ) -> None:
        """Validate + atomically write the GLOBAL XDG ``config.yaml``.

        Reuses the same secret-merge, changed-fields-only validation, and
        atomic-write (.bak) machinery as the per-project path. Creates the XDG
        config directory if it does not yet exist."""
        path = self._global_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Global layer inherits only from the code default.
        self._write_to(path, values, unset, inherit_from={})

    @staticmethod
    def _strip_inherited_noise(
        merged: dict[str, Any],
        existing: dict[str, Any],
        inherit_from: dict[str, Any],
    ) -> None:
        """Keep the config sparse: drop a NEWLY-added leaf that equals the value
        it would inherit anyway.

        The dashboard form submits a field's effective value even when it only
        inherits it (e.g. ``embedding.model`` materialized to its code default).
        Persisting that would un-sparse the file and re-introduce the verbatim
        "copy the inherited value into the project" writes the config model
        forbids — and make every later save diff it as a change. So a leaf that
        (a) was NOT already set on disk and (b) equals its inherited value
        (``inherit_from`` layer, else the code default) is removed before write.
        A value that DIVERGES from what it would inherit is a real override and
        is kept; a leaf the user already had on disk is left untouched.
        """
        flat_old = _flatten(existing)
        for dp, val in list(_flatten(merged).items()):
            if dp in flat_old:
                continue  # pre-existing project value — never auto-strip
            if dp in inherit_from:
                inherited = inherit_from[dp]
            elif dp in DEFAULTS:
                inherited = DEFAULTS[dp]
            else:
                continue  # nothing to inherit → a genuine new override
            if val == inherited:
                _unset_dotpath(merged, dp)

    @staticmethod
    def _prefill_context_tokens(merged: dict[str, Any]) -> None:
        """Task 4e: when summarization.model is being set and the model is in the
        map, prefill extraction.provider_context_tokens (editable, sparse —
        written only when a known model is selected, never overwriting a
        user-set value)."""
        try:
            from brainpalace_server.config.model_windows import window_for

            summ = merged.get("summarization")
            if not isinstance(summ, dict):
                return
            provider = str(summ.get("provider") or "")
            model = str(summ.get("model") or "")
            if not provider or not model:
                return
            tokens = window_for(provider, model)
            if tokens is None:
                return
            ext = merged.setdefault("extraction", {})
            if not isinstance(ext, dict):
                return
            # Only prefill if the user hasn't explicitly set a value already.
            if "provider_context_tokens" not in ext:
                ext["provider_context_tokens"] = tokens
        except Exception:  # noqa: BLE001 — never block a dashboard save
            pass

    def _write_to(
        self,
        path: Path,
        values: dict[str, Any],
        unset: list[str] | tuple[str, ...] = (),
        inherit_from: dict[str, Any] | None = None,
    ) -> None:
        existing = yaml.safe_load(path.read_text()) if path.exists() else {}
        merged = _merge_secrets(values, existing or {})
        # Task 4e: prefill extraction.provider_context_tokens when model is known.
        if "summarization" in merged:
            self._prefill_context_tokens(merged)
        # Staged inherit: the form sends the keys it wants REMOVED so they fall
        # back to global / code default. Apply them in the SAME atomic write as
        # the value sets, so "revert to inherited" only persists on Save (and a
        # Discard / refresh before Save reverts it — it was never written).
        for dotpath in unset:
            _unset_dotpath(merged, dotpath)
        if inherit_from is not None:
            self._strip_inherited_noise(merged, existing or {}, inherit_from)
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
        self._atomic_write(path, merged)

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, Any]) -> None:
        """Persist ``data`` to ``path`` atomically, keeping a ``.bak`` copy."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False))
        if path.exists():
            path.replace(path.with_suffix(".yaml.bak"))
        os.replace(tmp, path)

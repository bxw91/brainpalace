# Dashboard Plan 02 — ConfigService + UISchema generator + config API

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development / executing-plans. Read [index](2026-06-04-server-dashboard-00-index.md) first. Depends on plan 01.

**Goal:** Generate a complete UISchema from `config_schema.py` (so every config field renders as a click-only control automatically) and expose read/validate/write of each instance's `config.yaml` with batched, all-or-nothing PATCH + optional restart.

**Architecture:** `ConfigService` reads/writes `<state_dir>/config.yaml` atomically, masks secrets, validates with `validate_config_dict`. `build_ui_schema()` walks `config_schema` constants and layers `ui_schema.py` presentation overrides. The Config form is 100% data-driven by `GET /dashboard/api/schema`.

**Tech Stack:** Python, PyYAML (via cli), FastAPI.

---

## File Structure
- Create `brainpalace_dashboard/services/config_svc.py` — read/write/validate/mask.
- Create `brainpalace_dashboard/ui_schema.py` — `build_ui_schema()` + override layer + `DASHBOARD_HIDDEN_FIELDS`.
- Create `brainpalace_dashboard/api/routes_config.py` — `/schema`, `/instances/{id}/config`.
- Modify `app.py` — include router.

---

### Task 2.1: `build_ui_schema()` — derive widgets from `config_schema`

**Files:**
- Create: `brainpalace_dashboard/ui_schema.py`
- Test: `brainpalace-dashboard/tests/test_ui_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_ui_schema.py
from brainpalace_dashboard.ui_schema import build_ui_schema, DASHBOARD_HIDDEN_FIELDS
from brainpalace_cli import config_schema as cs


def test_every_known_field_is_present_or_hidden():
    """Every config_schema field appears in the UISchema or is explicitly hidden."""
    ui = build_ui_schema()
    rendered = {f"{sec['key']}.{fld['key']}" for sec in ui["sections"] for fld in sec["fields"]}
    expected = set()
    section_fields = {
        "embedding": cs.EMBEDDING_KNOWN_FIELDS,
        "summarization": cs.SUMMARIZATION_KNOWN_FIELDS,
        "reranker": cs.RERANKER_KNOWN_FIELDS,
        "storage": cs.STORAGE_KNOWN_FIELDS,
        "graphrag": cs.GRAPHRAG_KNOWN_FIELDS,
        "api": cs.API_KNOWN_FIELDS,
        "server": cs.SERVER_KNOWN_FIELDS,
        "project": cs.PROJECT_KNOWN_FIELDS,
    }
    for sec, fields in section_fields.items():
        for fld in fields:
            expected.add(f"{sec}.{fld}")
    missing = expected - rendered - set(DASHBOARD_HIDDEN_FIELDS)
    assert not missing, f"config fields missing from UISchema: {sorted(missing)}"


def test_provider_field_is_enum_with_options():
    ui = build_ui_schema()
    emb = next(s for s in ui["sections"] if s["key"] == "embedding")
    provider = next(f for f in emb["fields"] if f["key"] == "provider")
    assert provider["widget"] == "enum"
    assert set(provider["options"]) == set(cs.VALID_EMBEDDING_PROVIDERS)


def test_graphrag_enabled_is_toggle():
    ui = build_ui_schema()
    g = next(s for s in ui["sections"] if s["key"] == "graphrag")
    enabled = next(f for f in g["fields"] if f["key"] == "enabled")
    assert enabled["widget"] == "toggle"


def test_api_key_is_secret():
    ui = build_ui_schema()
    emb = next(s for s in ui["sections"] if s["key"] == "embedding")
    key = next(f for f in emb["fields"] if f["key"] == "api_key")
    assert key["secret"] is True
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_ui_schema.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `ui_schema.py`**

```python
# brainpalace-dashboard/brainpalace_dashboard/ui_schema.py
"""Generate a UI form schema from config_schema (single source of truth).

Every known config field renders automatically. The OVERRIDES dict only
improves presentation (labels, presets, bounds, secret flags, visibility).
Fields intentionally not rendered must be listed in DASHBOARD_HIDDEN_FIELDS
with a reason — enforced by the parity gate (plan 08).
"""

from __future__ import annotations

from typing import Any

from brainpalace_cli import config_schema as cs

# Section render order + human labels.
SECTION_ORDER: list[tuple[str, str]] = [
    ("embedding", "Embedding"),
    ("summarization", "Summarization"),
    ("reranker", "Reranker"),
    ("storage", "Storage"),
    ("graphrag", "GraphRAG"),
    ("api", "API"),
    ("server", "Server"),
    ("project", "Project"),
]

SECTION_KNOWN: dict[str, set[str]] = {
    "embedding": cs.EMBEDDING_KNOWN_FIELDS,
    "summarization": cs.SUMMARIZATION_KNOWN_FIELDS,
    "reranker": cs.RERANKER_KNOWN_FIELDS,
    "storage": cs.STORAGE_KNOWN_FIELDS,
    "graphrag": cs.GRAPHRAG_KNOWN_FIELDS,
    "api": cs.API_KNOWN_FIELDS,
    "server": cs.SERVER_KNOWN_FIELDS,
    "project": cs.PROJECT_KNOWN_FIELDS,
}

# field dotpath -> enum options (from config_schema enum sets).
ENUM_OPTIONS: dict[str, list[str]] = {
    "embedding.provider": sorted(cs.VALID_EMBEDDING_PROVIDERS),
    "summarization.provider": sorted(cs.VALID_SUMMARIZATION_PROVIDERS),
    "reranker.provider": sorted(cs.VALID_RERANKER_PROVIDERS),
    "storage.backend": sorted(cs.VALID_STORAGE_BACKENDS),
    "graphrag.store_type": sorted(cs.VALID_GRAPHRAG_STORE_TYPES),
    "graphrag.doc_extractor": sorted(cs.VALID_DOC_EXTRACTORS),
}

# Presentation overrides ONLY. Keys are dotpaths.
OVERRIDES: dict[str, dict[str, Any]] = {
    "embedding.api_key": {"secret": True, "label": "API key (inline — prefer env var)"},
    "summarization.api_key": {"secret": True, "label": "API key (inline — prefer env var)"},
    "storage.postgres.password": {"secret": True},
    "embedding.api_key_env": {"label": "API key env var", "placeholder": "OPENAI_API_KEY"},
    "summarization.api_key_env": {"label": "API key env var", "placeholder": "ANTHROPIC_API_KEY"},
    "embedding.model": {"presets": ["text-embedding-3-small", "text-embedding-3-large", "nomic-embed-text"]},
    "summarization.model": {"presets": ["claude-3-5-haiku-latest", "claude-sonnet-4-6", "gpt-4o-mini"]},
    "server.port": {"min": 1, "max": 65535, "step": 1},
    "api.port": {"min": 1, "max": 65535, "step": 1},
    "graphrag.use_code_metadata": {"label": "Use code metadata"},
    # postgres section is only meaningful when storage.backend == postgres
    "storage.postgres": {"visible_when": {"field": "storage.backend", "equals": "postgres"}},
}

# Fields deliberately not shown in the form (parity gate requires a reason).
DASHBOARD_HIDDEN_FIELDS: dict[str, str] = {
    "project.state_dir": "internal path, set by init; editing breaks discovery",
    "project.project_root": "internal path, set by init; editing breaks discovery",
}

# Type hints from config_schema (int/bool). Defaults to text otherwise.
_INT_FIELDS = {"server.port", "api.port"} | {f"storage.postgres.{k}" for k, (t, _) in cs.POSTGRES_TYPE_FIELDS.items() if t is int}
_BOOL_FIELDS = {"graphrag.enabled", "server.auto_port", "graphrag.use_code_metadata"} | {
    f"storage.postgres.{k}" for k, (t, _) in cs.POSTGRES_TYPE_FIELDS.items() if t is bool
}


def _widget_for(dotpath: str) -> str:
    if dotpath in ENUM_OPTIONS:
        return "enum"
    if dotpath in _BOOL_FIELDS:
        return "toggle"
    if dotpath in _INT_FIELDS:
        return "int"
    return "text"


def _field(section: str, key: str) -> dict[str, Any]:
    dotpath = f"{section}.{key}"
    ov = OVERRIDES.get(dotpath, {})
    field: dict[str, Any] = {
        "key": key,
        "dotpath": dotpath,
        "label": ov.get("label", key.replace("_", " ").capitalize()),
        "widget": _widget_for(dotpath),
        "secret": bool(ov.get("secret", False)),
    }
    if field["widget"] == "enum":
        field["options"] = ENUM_OPTIONS[dotpath]
    for opt_key in ("presets", "placeholder", "min", "max", "step", "help", "visible_when"):
        if opt_key in ov:
            field[opt_key] = ov[opt_key]
    return field


def build_ui_schema() -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for key, label in SECTION_ORDER:
        known = sorted(SECTION_KNOWN[key])
        fields = []
        for fld in known:
            dotpath = f"{key}.{fld}"
            if dotpath in DASHBOARD_HIDDEN_FIELDS:
                continue
            # "postgres" is a nested object inside storage — expand it.
            if dotpath == "storage.postgres":
                continue  # handled as nested below
            fields.append(_field(key, fld))
        if key == "storage":
            fields.append({
                "key": "postgres",
                "dotpath": "storage.postgres",
                "label": "PostgreSQL",
                "widget": "group",
                "visible_when": {"field": "storage.backend", "equals": "postgres"},
                "fields": [_field("storage.postgres", k) for k in sorted(cs.POSTGRES_KNOWN_FIELDS)],
            })
        sections.append({"key": key, "label": label, "fields": fields})
    return {"sections": sections}
```

> Note: `storage.postgres` is a nested object, so it is rendered as a `group` widget with child fields, and excluded from the flat `storage` loop. The parity test in plan 08 accounts for nested groups.

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_ui_schema.py -v`
Expected: PASS. If `test_every_known_field_is_present_or_hidden` fails for a field, either add it to a section render path or to `DASHBOARD_HIDDEN_FIELDS` with a reason.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/ui_schema.py brainpalace-dashboard/tests/test_ui_schema.py
git commit -m "feat(dashboard): generate UISchema from config_schema

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2.2: `ConfigService` — read + mask secrets

**Files:**
- Create: `brainpalace_dashboard/services/config_svc.py`
- Test: `brainpalace-dashboard/tests/test_config_read.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_config_read.py
from pathlib import Path
from brainpalace_dashboard.services.config_svc import ConfigService


def test_read_masks_secrets(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  api_key: sk-SECRET123\n  api_key_env: OPENAI_API_KEY\n"
    )
    svc = ConfigService()
    values = svc.read(state)
    assert values["embedding"]["provider"] == "openai"
    assert values["embedding"]["api_key"] == "********"     # masked
    assert values["embedding"]["api_key_env"] == "OPENAI_API_KEY"  # not secret
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_config_read.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement read + masking**

```python
# brainpalace-dashboard/brainpalace_dashboard/services/config_svc.py
"""ConfigService: read/validate/write config.yaml; mask secrets."""

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
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in values.items()}
    for dotpath in SECRET_DOTPATHS:
        parts = dotpath.split(".")
        node = out
        for p in parts[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                node = None
                break
        if isinstance(node, dict) and parts[-1] in node and node[parts[-1]]:
            node[parts[-1]] = MASK
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_config_read.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/services/config_svc.py brainpalace-dashboard/tests/test_config_read.py
git commit -m "feat(dashboard): ConfigService read with secret masking

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2.3: `ConfigService.write` — validate, preserve masked secrets, atomic, .bak

**Files:**
- Modify: `brainpalace_dashboard/services/config_svc.py`
- Test: `brainpalace-dashboard/tests/test_config_write.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_config_write.py
import yaml
import pytest
from brainpalace_dashboard.services.config_svc import ConfigService, MASK, ConfigWriteError


def _state(tmp_path, body):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(body)
    return state


def test_write_rejects_invalid_and_keeps_file(tmp_path):
    state = _state(tmp_path, "embedding:\n  provider: openai\n")
    svc = ConfigService()
    with pytest.raises(ConfigWriteError) as ei:
        svc.write(state, {"embedding": {"provider": "not-a-provider"}})
    assert ei.value.errors  # has field-level errors
    # original file unchanged
    assert "openai" in (state / "config.yaml").read_text()


def test_write_preserves_existing_secret_when_value_is_mask(tmp_path):
    state = _state(tmp_path, "embedding:\n  provider: openai\n  api_key: sk-REAL\n")
    svc = ConfigService()
    svc.write(state, {"embedding": {"provider": "openai", "api_key": MASK}})
    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["embedding"]["api_key"] == "sk-REAL"   # mask did not overwrite real secret


def test_write_atomic_creates_bak(tmp_path):
    state = _state(tmp_path, "embedding:\n  provider: openai\n")
    svc = ConfigService()
    svc.write(state, {"embedding": {"provider": "ollama"}})
    assert (state / "config.yaml.bak").exists()
    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["embedding"]["provider"] == "ollama"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_config_write.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement write + error type**

Add to `config_svc.py`:

```python
class ConfigWriteError(Exception):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__(f"{len(errors)} config validation error(s)")


def _merge_secrets(new: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Replace any MASK value in ``new`` with the real value from ``existing``."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in new.items()}
    for dotpath in SECRET_DOTPATHS:
        parts = dotpath.split(".")
        nnode, enode = out, existing
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
```

Add methods to `ConfigService`:

```python
    def validate(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        errs = validate_config_dict(values)
        # Only block on hard errors; treat unknown-key warnings as non-blocking.
        blocking = [e for e in errs if getattr(e, "severity", "error") != "warning"]
        return [
            {"field": e.field, "message": e.message, "suggestion": e.suggestion}
            for e in blocking
        ]

    def write(self, state_dir, values: dict[str, Any]) -> None:
        from pathlib import Path
        state_dir = Path(state_dir)
        path = self._config_path(state_dir)
        existing = yaml.safe_load(path.read_text()) if path.exists() else {}
        merged = _merge_secrets(values, existing or {})
        errors = self.validate(merged)
        if errors:
            raise ConfigWriteError(errors)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(merged, sort_keys=False))
        if path.exists():
            path.replace(path.with_suffix(".yaml.bak"))
        os.replace(tmp, path)
```

> Check whether `ConfigValidationError` has a `severity` attribute; the constructor in `config_schema.py` is `ConfigValidationError(field, message, line_number, suggestion)`. If there's no severity field, treat all returned items as blocking and drop the `severity` filter (read the validate function to see if it separates warnings from errors; mirror its behavior).

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_config_write.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/services/config_svc.py brainpalace-dashboard/tests/test_config_write.py
git commit -m "feat(dashboard): atomic validated config write preserving secrets

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2.4: Config REST routes (`/schema`, GET/PATCH config, optional restart)

**Files:**
- Create: `brainpalace_dashboard/api/routes_config.py`
- Modify: `app.py`
- Test: `brainpalace-dashboard/tests/test_routes_config.py`

- [ ] **Step 1: Write the failing test**

```python
# brainpalace-dashboard/tests/test_routes_config.py
from fastapi.testclient import TestClient
import brainpalace_dashboard.api.routes_config as rc
from brainpalace_dashboard.app import create_app


def test_schema_route():
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/schema")
    assert resp.status_code == 200
    assert any(s["key"] == "embedding" for s in resp.json()["sections"])


def test_get_config_route(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    client = TestClient(create_app())
    resp = client.get("/dashboard/api/instances/abc/config")
    assert resp.json()["embedding"]["provider"] == "openai"


def test_patch_config_validation_error(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/config",
        json={"values": {"embedding": {"provider": "bogus"}}, "restart": False},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]


def test_patch_config_ok_with_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "_state_dir_for", lambda id_: tmp_path)
    (tmp_path / "config.yaml").write_text("embedding:\n  provider: openai\n")
    restarted = {}
    monkeypatch.setattr(rc.instance_service, "restart", lambda id_: restarted.setdefault("x", True))
    client = TestClient(create_app())
    resp = client.patch(
        "/dashboard/api/instances/abc/config",
        json={"values": {"embedding": {"provider": "ollama"}}, "restart": True},
    )
    assert resp.status_code == 200
    assert resp.json()["restarted"] is True
    assert restarted == {"x": True}
```

- [ ] **Step 2: Run to verify fail**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_routes_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement routes + wire app**

```python
# brainpalace-dashboard/brainpalace_dashboard/api/routes_config.py
"""Config schema + per-instance config GET/PATCH."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from brainpalace_dashboard.services.config_svc import ConfigService, ConfigWriteError
from brainpalace_dashboard.services.instances import InstanceService, InstanceNotFound

router = APIRouter(prefix="/dashboard/api", tags=["config"])
config_service = ConfigService()
instance_service = InstanceService()


def _state_dir_for(id_: str) -> Path:
    entry = instance_service._resolve(id_)  # raises InstanceNotFound
    root = Path(entry["project_root"])
    return Path(entry["state_dir"]) if entry.get("state_dir") else root / ".brainpalace"


class ConfigPatch(BaseModel):
    values: dict
    restart: bool = False


@router.get("/schema")
def get_schema() -> dict:
    return config_service.schema()


@router.get("/instances/{id_}/config")
def get_config(id_: str) -> dict:
    try:
        return config_service.read(_state_dir_for(id_))
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found")


@router.patch("/instances/{id_}/config")
def patch_config(id_: str, body: ConfigPatch) -> dict:
    try:
        state_dir = _state_dir_for(id_)
    except InstanceNotFound:
        raise HTTPException(status_code=404, detail="instance not found")
    try:
        config_service.write(state_dir, body.values)
    except ConfigWriteError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors})
    restarted = False
    if body.restart:
        try:
            instance_service.restart(id_)
            restarted = True
        except Exception as e:  # surface but don't lose the saved config
            return {"ok": True, "restarted": False, "restart_error": str(e)}
    return {"ok": True, "restarted": restarted}
```

> FastAPI returns `detail` for HTTPException; the test reads `resp.json()["errors"]`. Adjust the 422 to `raise HTTPException(status_code=422, detail=...)` and in the test read `resp.json()["detail"]["errors"]`, OR raise a custom JSONResponse. Pick one and make test + code consistent. (Recommended: custom `JSONResponse(status_code=422, content={"errors": e.errors})` so the body is exactly `{"errors": [...]}`.)

Wire in `app.py`: `from brainpalace_dashboard.api import routes_config` and `app.include_router(routes_config.router)`.

- [ ] **Step 4: Run to verify pass**

Run: `cd brainpalace-dashboard && poetry run pytest tests/test_routes_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add brainpalace-dashboard/brainpalace_dashboard/api/routes_config.py brainpalace-dashboard/brainpalace_dashboard/app.py brainpalace-dashboard/tests/test_routes_config.py
git commit -m "feat(dashboard): config schema + GET/PATCH config routes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Plan 02 self-check
- [ ] `GET /dashboard/api/schema` returns all sections; every `config_schema` field present or in `DASHBOARD_HIDDEN_FIELDS`.
- [ ] PATCH validates (422 on bad enum), preserves masked secrets, writes atomically with `.bak`, restarts when asked.
- [ ] `task test:dashboard` + `task check` green.

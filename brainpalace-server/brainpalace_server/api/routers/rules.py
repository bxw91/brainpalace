"""Taught confidence rules API — list/add/get/retire (Phase 5 / CO-3)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter()


def _rule_store(request: Request) -> Any:
    rs = getattr(request.app.state, "taught_rule_store", None)
    if rs is None:
        raise HTTPException(status_code=503, detail="TaughtRuleStore unavailable.")
    return rs


@router.get("", summary="List taught rules")
async def list_rules(request: Request, active: bool = True) -> dict[str, Any]:
    return {"rules": _rule_store(request).list_rules(active_only=active)}


@router.post("", summary="Add (teach) a confidence rule")
async def add_rule(body: dict[str, Any], request: Request) -> dict[str, str]:
    store = _rule_store(request)
    try:
        rid = store.add_rule(
            owner=body.get("owner", "user"),
            metric=body["metric"],
            tier=body["tier"],
            unit=body.get("unit"),
            value_min=body.get("value_min"),
            value_max=body.get("value_max"),
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"missing field: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _reload(request, metric=body["metric"])  # scope re-score to this metric
    return {"id": rid}


@router.get("/{rule_id}", summary="Get one taught rule")
async def get_rule(rule_id: str, request: Request) -> dict[str, Any]:
    rule = _rule_store(request).get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return dict(rule)


@router.post("/{rule_id}/retire", summary="Retire (soft-delete) a taught rule")
async def retire_rule(rule_id: str, request: Request) -> dict[str, bool]:
    store = _rule_store(request)
    rule = store.get_rule(rule_id)  # capture metric before we lose the active row
    retired = store.retire_rule(rule_id)
    _reload(request, metric=rule["metric"] if rule else None)
    return {"retired": retired}


def _reload(request: Request, *, metric: str | None = None) -> None:
    """Recompile validators + re-score records after a rule change (Finding D:
    scoped to the changed metric)."""
    from brainpalace_server.indexing.taught_rules import reload_taught_rules

    reload_taught_rules(
        _rule_store(request),
        getattr(request.app.state, "record_store", None),
        metric=metric,
    )

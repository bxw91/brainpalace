"""Compile durable declarative rules into confidence validators (Phase 5).

A row from TaughtRuleStore is a declarative predicate; compile_rule turns it
into the Callable[[RecordCandidate], float] that register_validator expects.
Aggregation is max (record_validation.score_confidence) → rules promote only
(unmatched predicate abstains with 0.0).
"""

from __future__ import annotations

from typing import Any

from brainpalace_server.indexing.record_validation import (
    HIGH_CONFIDENCE,
    PROVISIONAL_CONFIDENCE,
    UNVERIFIED_CONFIDENCE,
    Validator,
    register_validator,
    reset_validators,
    score_confidence,
)
from brainpalace_server.models.record import RecordCandidate

_TIER = {
    "HIGH": HIGH_CONFIDENCE,
    "PROVISIONAL": PROVISIONAL_CONFIDENCE,
    "UNVERIFIED": UNVERIFIED_CONFIDENCE,
}


def compile_rule(rule: dict[str, Any]) -> Validator:
    metric = rule["metric"]
    unit = rule.get("unit")
    lo = rule.get("value_min")
    hi = rule.get("value_max")
    tier_value = _TIER[rule["tier"]]

    def _validator(c: RecordCandidate) -> float:
        if c.metric != metric:
            return 0.0
        if unit is not None and c.unit != unit:
            return 0.0
        if lo is not None and c.value < lo:
            return 0.0
        if hi is not None and c.value > hi:
            return 0.0
        return tier_value

    return _validator


def load_taught_rules(rule_store: Any) -> int:
    """Register every active rule as a validator. Returns count registered."""
    n = 0
    for rule in rule_store.list_rules(active_only=True):
        register_validator(compile_rule(rule))
        n += 1
    return n


def reload_taught_rules(
    rule_store: Any, record_store: Any, *, metric: str | None = None
) -> int:
    """Rebuild the validator list from scratch (baseline + active rules), then
    re-score records' confidence (below=2.0 > any confidence in [0,1]) so an
    added rule promotes and a retired rule drops back to baseline. Scoped to
    ``metric`` when given (Finding D — a rule change only affects its own
    metric's records); else re-scores all. Returns rows re-scored (0 when no
    record store)."""
    reset_validators()
    load_taught_rules(rule_store)
    if record_store is None:
        return 0
    return int(record_store.revalidate(score_confidence, metric=metric, below=2.0))

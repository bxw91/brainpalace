import pytest

from brainpalace_server.storage.taught_rule_store import TaughtRuleStore


def _store(tmp_path):
    return TaughtRuleStore(tmp_path / "rules.db")


def test_add_and_list(tmp_path):
    s = _store(tmp_path)
    rid = s.add_rule(
        owner="user",
        metric="weight",
        unit="kg",
        value_min=60,
        value_max=120,
        tier="HIGH",
    )
    rules = s.list_rules()
    assert len(rules) == 1
    r = rules[0]
    assert r["id"] == rid and r["metric"] == "weight" and r["tier"] == "HIGH"
    assert r["version"] == 1 and r["retired_at"] is None


def test_add_identical_is_idempotent(tmp_path):
    s = _store(tmp_path)
    a = s.add_rule(owner="user", metric="weight", tier="HIGH")
    b = s.add_rule(owner="user", metric="weight", tier="HIGH")
    assert a == b and len(s.list_rules()) == 1


def test_edit_retires_prior_and_bumps_version(tmp_path):
    # Finding C: editing a rule (same owner+metric+unit, new bound) replaces the
    # prior version — exactly one active, both versions preserved in history.
    s = _store(tmp_path)
    s.add_rule(owner="user", metric="weight", unit="kg", value_max=120, tier="HIGH")
    s.add_rule(owner="user", metric="weight", unit="kg", value_max=130, tier="HIGH")
    active = s.list_rules(active_only=True)
    assert len(active) == 1 and active[0]["value_max"] == 130
    assert active[0]["version"] == 2
    assert len(s.list_rules(active_only=False)) == 2


def test_different_unit_coexists(tmp_path):
    # Same metric, different unit → different supersession key → both stay active.
    s = _store(tmp_path)
    s.add_rule(owner="user", metric="weight", unit="kg", tier="HIGH")
    s.add_rule(owner="user", metric="weight", unit="lb", tier="HIGH")
    assert len(s.list_rules(active_only=True)) == 2


def test_retire_soft_deletes(tmp_path):
    s = _store(tmp_path)
    rid = s.add_rule(owner="user", metric="weight", tier="HIGH")
    assert s.retire_rule(rid) is True
    assert s.list_rules(active_only=True) == []
    assert len(s.list_rules(active_only=False)) == 1
    assert s.retire_rule(rid) is False  # already retired → no-op


def test_readd_retired_reactivates(tmp_path):
    s = _store(tmp_path)
    rid = s.add_rule(owner="user", metric="weight", tier="HIGH")
    s.retire_rule(rid)
    again = s.add_rule(owner="user", metric="weight", tier="HIGH")
    assert again == rid
    assert s.get_rule(rid)["retired_at"] is None


def test_invalid_tier_rejected(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValueError):
        s.add_rule(owner="user", metric="weight", tier="MAYBE")


def test_bad_bounds_rejected(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(ValueError):
        s.add_rule(
            owner="user", metric="weight", value_min=120, value_max=60, tier="HIGH"
        )

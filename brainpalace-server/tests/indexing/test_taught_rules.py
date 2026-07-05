from brainpalace_server.indexing import record_validation
from brainpalace_server.indexing.taught_rules import (
    compile_rule,
    load_taught_rules,
    reload_taught_rules,
)
from brainpalace_server.models.record import Record, RecordCandidate
from brainpalace_server.storage.record_store import RecordStore
from brainpalace_server.storage.taught_rule_store import TaughtRuleStore


def teardown_function():
    record_validation.reset_validators()


def _cand(metric, value, unit=None):
    return RecordCandidate(subject="s", metric=metric, value=value, unit=unit)


def test_compile_in_range_returns_tier():
    v = compile_rule(
        {
            "metric": "weight",
            "unit": "kg",
            "value_min": 60,
            "value_max": 120,
            "tier": "HIGH",
        }
    )
    assert v(_cand("weight", 80, "kg")) == record_validation.HIGH_CONFIDENCE
    assert v(_cand("weight", 200, "kg")) == 0.0  # out of range → abstain
    assert v(_cand("height", 80, "kg")) == 0.0  # wrong metric → abstain
    assert v(_cand("weight", 80, "lb")) == 0.0  # wrong unit → abstain


def test_compile_open_bounds():
    v = compile_rule({"metric": "m", "value_min": 10, "tier": "PROVISIONAL"})
    assert v(_cand("m", 50)) == record_validation.PROVISIONAL_CONFIDENCE
    assert v(_cand("m", 5)) == 0.0


def test_load_registers_active_rules(tmp_path):
    rs = TaughtRuleStore(tmp_path / "rules.db")
    rs.add_rule(owner="user", metric="weight", value_min=60, value_max=120, tier="HIGH")
    record_validation.reset_validators()
    assert load_taught_rules(rs) == 1
    assert (
        record_validation.score_confidence(_cand("weight", 80))
        == record_validation.HIGH_CONFIDENCE
    )


def test_reload_promotes_then_retire_demotes(tmp_path):
    rs = TaughtRuleStore(tmp_path / "rules.db")
    store = RecordStore(tmp_path / "records.db")
    # a distance record numeric-sanity-only scores 0.6 by default
    store.insert_records(
        [Record(id="a", subject="s", metric="distance", value=5.0, confidence=0.6)]
    )
    rid = rs.add_rule(
        owner="user", metric="distance", value_min=0, value_max=10, tier="HIGH"
    )
    reload_taught_rules(rs, store, metric="distance")
    c = store._conn.execute("SELECT confidence FROM records WHERE id='a'").fetchone()
    assert c[0] == record_validation.HIGH_CONFIDENCE  # promoted
    rs.retire_rule(rid)
    reload_taught_rules(rs, store, metric="distance")
    c = store._conn.execute("SELECT confidence FROM records WHERE id='a'").fetchone()
    assert c[0] == record_validation.PROVISIONAL_CONFIDENCE  # back to baseline


def test_reload_metric_scope_leaves_others(tmp_path):
    # Finding D: a rule change only re-scores its own metric's records.
    rs = TaughtRuleStore(tmp_path / "rules.db")
    store = RecordStore(tmp_path / "records.db")
    store.insert_records(
        [Record(id="b", subject="s", metric="weight", value=5.0, confidence=0.42)]
    )
    rs.add_rule(owner="user", metric="distance", tier="HIGH")
    reload_taught_rules(rs, store, metric="distance")
    # unrelated 'weight' row untouched (its odd 0.42 confidence is preserved)
    c = store._conn.execute("SELECT confidence FROM records WHERE id='b'").fetchone()
    assert c[0] == 0.42

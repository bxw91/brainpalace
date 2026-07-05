from brainpalace_server.indexing import record_validation
from brainpalace_server.indexing.record_validation import score_confidence
from brainpalace_server.models.record import RecordCandidate
from brainpalace_server.storage.taught_rule_store import TaughtRuleStore


def teardown_function():
    record_validation.reset_validators()


def test_startup_loads_persisted_rules(tmp_path):
    """A rule persisted before 'restart' is active after a fresh load."""
    rs = TaughtRuleStore(tmp_path / "rules.db")
    rs.add_rule(owner="user", metric="weight", value_min=60, value_max=120, tier="HIGH")
    # simulate restart: fresh registry + reload from the same db
    record_validation.reset_validators()
    from brainpalace_server.indexing.taught_rules import load_taught_rules

    load_taught_rules(TaughtRuleStore(tmp_path / "rules.db"))
    cand = RecordCandidate(subject="s", metric="weight", value=80.0)
    assert score_confidence(cand) == record_validation.HIGH_CONFIDENCE

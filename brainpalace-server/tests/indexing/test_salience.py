from datetime import datetime, timedelta, timezone

from brainpalace_server.indexing import salience
from brainpalace_server.models.record import Record


def _rec(ts, domain="code"):
    return Record(
        id="x", subject="s", metric="m", value=1.0, unit=None, ts=ts, domain=domain
    )


def teardown_function():
    salience.reset_salience_scorers()


def test_recent_ts_scores_near_one():
    now = datetime.now(timezone.utc).isoformat()
    assert salience.score_salience(_rec(now)) > 0.99


def test_old_ts_scores_lower_than_recent():
    old = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    assert salience.score_salience(_rec(old)) < salience.score_salience(_rec(recent))


def test_missing_ts_no_penalty():
    assert salience.score_salience(_rec(None)) == 1.0


def test_scorer_sees_domain():
    # Finding B: a scorer can key on domain, unavailable on RecordCandidate.
    salience.register_salience_scorer(lambda r: 0.1 if r.domain == "chat-life" else 0.0)
    assert salience.score_salience(_rec(None, domain="chat-life")) >= 0.1


def test_registered_scorer_participates_in_max():
    salience.register_salience_scorer(lambda r: 1.0)
    old = (datetime.now(timezone.utc) - timedelta(days=3650)).isoformat()
    assert salience.score_salience(_rec(old)) == 1.0


def test_reset_reseeds_default_only():
    salience.register_salience_scorer(lambda r: 0.5)
    salience.reset_salience_scorers()
    assert salience.score_salience(_rec(None)) == 1.0

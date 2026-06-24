import pytest

from brainpalace_server.indexing import record_validation as rv
from brainpalace_server.indexing.record_validation import (
    HIGH_CONFIDENCE,
    PROVISIONAL_CONFIDENCE,
    UNVERIFIED_CONFIDENCE,
    register_validator,
    score_confidence,
)
from brainpalace_server.models.record import RecordCandidate


@pytest.fixture(autouse=True)
def _reset():
    saved = list(rv._VALIDATORS)
    yield
    rv._VALIDATORS[:] = saved  # finding #9


def _cand(subject, metric, value, unit=None):
    return RecordCandidate(subject=subject, metric=metric, value=value, unit=unit)


def test_authored_currency_is_high():
    assert score_confidence(_cand("amount", "amount", 10.0, "USD")) == HIGH_CONFIDENCE


def test_authored_count_metric_is_high():
    c = _cand("session", "files_touched", 3.0, "count")
    assert score_confidence(c) == HIGH_CONFIDENCE


def test_novel_numeric_metric_is_provisional():
    c = _cand("weight", "bodyweight", 80.0, "kg")
    assert score_confidence(c) == PROVISIONAL_CONFIDENCE


def test_registered_validator_promotes():
    register_validator(lambda c: 1.0 if c.metric == "bodyweight" else 0.0)
    c = _cand("weight", "bodyweight", 80.0, "kg")
    assert score_confidence(c) == HIGH_CONFIDENCE


def test_non_finite_is_unverified():
    assert score_confidence(_cand("x", "x", float("inf"))) == UNVERIFIED_CONFIDENCE

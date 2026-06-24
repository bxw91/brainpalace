import pytest
from pydantic import ValidationError

from brainpalace_server.models.record import Record, RecordCandidate


def test_candidate_minimal():
    c = RecordCandidate(subject="sales", metric="amount", value=4200.0, unit="USD")
    assert c.value == 4200.0 and c.ts is None


def test_candidate_forbids_extra_keys():
    with pytest.raises(ValidationError):
        RecordCandidate(subject="s", metric="m", value=1.0, bogus=1)


def test_record_defaults_provenance_and_domain():
    r = Record(id="r1", subject="sales", metric="amount", value=4200.0)
    assert r.domain == "code" and r.confidence == 0.0 and r.source is None


def test_record_is_frozen():
    r = Record(id="r1", subject="s", metric="m", value=1.0)
    with pytest.raises(ValidationError):
        r.value = 2.0

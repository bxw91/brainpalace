import pytest

from brainpalace_server.indexing import record_extractors as rx
from brainpalace_server.models.record import RecordCandidate


@pytest.fixture(autouse=True)
def _reset():
    saved = list(rx._EXTRACTORS)
    yield
    rx._EXTRACTORS[:] = saved  # restore — no cross-test leakage (finding #9)


def test_rule_extracts_currency_amount():
    out = rx.rule_extract("Closed $4,200 in sales today.")
    assert any(c.value == 4200.0 and c.unit == "USD" for c in out)


def test_registry_runs_custom_extractor():
    rx.register_extractor(
        lambda t: (
            [RecordCandidate(subject="x", metric="m", value=1.0)]
            if "MAGIC" in t
            else []
        )
    )
    assert any(c.metric == "m" for c in rx.extract_records("MAGIC here"))

from brainpalace_server.models.record import Record


def _rec(**kw):
    base = {"id": "1", "subject": "s", "metric": "m", "value": 1.0}
    base.update(kw)
    return Record(**base)


def test_sensitivity_defaults_normal():
    assert _rec().sensitivity == "normal"


def test_sensitivity_open_string():
    assert _rec(sensitivity="private").sensitivity == "private"

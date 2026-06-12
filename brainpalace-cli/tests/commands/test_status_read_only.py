"""status surfaces read-only + self-heal rows from the /health/status features."""

from brainpalace_cli.commands.status import _read_only_row, _self_heal_row


def test_read_only_row_on():
    row = _read_only_row({"read_only": True})
    assert row is not None
    label, value = row
    assert label == "Read-Only"
    assert "ON" in value.upper()


def test_read_only_row_absent():
    assert _read_only_row({"read_only": False}) is None
    assert _read_only_row({}) is None


def _heal(**last):
    return {"self_heal": {"last": last}}


def test_self_heal_read_only_skip_is_not_alarming():
    # The intentional read-only stage-2 skip must NOT render as a problem.
    row = _self_heal_row(
        _heal(restored=4878, recoverable=4878, incomplete_reason="read-only mode")
    )
    assert row is not None
    label, value = row
    assert label == "Self-Heal"
    assert "read-only" in value.lower()
    assert "recovered 4,878/4,878" in value
    assert "INCOMPLETE" not in value
    assert "fix + restart" not in value


def test_self_heal_genuine_incomplete_is_alarming():
    row = _self_heal_row(
        _heal(restored=10, recoverable=20, incomplete_reason="recovery incomplete")
    )
    assert row is not None
    assert "INCOMPLETE" in row[1]
    assert "fix + restart" in row[1]


def test_self_heal_error_is_alarming():
    row = _self_heal_row(_heal(restored=0, recoverable=0, error="boom"))
    assert row is not None
    assert "INCOMPLETE" in row[1]


def test_self_heal_complete_is_green():
    row = _self_heal_row(_heal(restored=100, files_dropped=5, residue=3))
    assert row is not None
    assert "restored 100 chunk(s)" in row[1]
    assert "5 file(s) re-indexing" in row[1]
    assert "3 chunk(s) need re-embed" in row[1]
    assert "INCOMPLETE" not in row[1]


def test_self_heal_absent():
    assert _self_heal_row({}) is None
    assert _self_heal_row({"self_heal": {}}) is None

"""Schema validation for server.read_only."""

from brainpalace_cli.config_schema import validate_config_dict


def test_server_read_only_bool_ok():
    errors = validate_config_dict({"server": {"read_only": True}})
    assert errors == []


def test_server_read_only_rejects_non_bool():
    errors = validate_config_dict({"server": {"read_only": "yes"}})
    assert any("read_only" in str(e) for e in errors)

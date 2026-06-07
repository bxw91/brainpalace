from brainpalace_cli import config_schema as cs


def test_query_log_is_valid_top_level():
    assert "query_log" in cs.VALID_TOP_LEVEL_KEYS


def test_query_log_known_fields():
    assert {"enabled", "retention_days"} <= cs.QUERY_LOG_KNOWN_FIELDS


def test_query_log_validates():
    errs = cs.validate_config_dict(
        {"query_log": {"enabled": True, "retention_days": 7}}
    )
    assert not [e for e in errs if e.field.startswith("query_log")]


def test_query_log_type_errors():
    errs = cs.validate_config_dict(
        {"query_log": {"enabled": "yes", "retention_days": "seven"}}
    )
    fields = {e.field for e in errs}
    assert "query_log.enabled" in fields
    assert "query_log.retention_days" in fields


def test_query_log_unknown_field_flagged():
    errs = cs.validate_config_dict({"query_log": {"bogus": 1}})
    assert any(e.field == "query_log.bogus" for e in errs)

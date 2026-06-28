"""Schema validation for server.read_only and extraction section."""

from brainpalace_cli.config_schema import validate_config_dict


def test_server_read_only_bool_ok():
    errors = validate_config_dict({"server": {"read_only": True}})
    assert errors == []


def test_server_read_only_rejects_non_bool():
    errors = validate_config_dict({"server": {"read_only": "yes"}})
    assert any("read_only" in str(e) for e in errors)


# ---------------------------------------------------------------------------
# Task 8 — extraction section validation (additive)
# ---------------------------------------------------------------------------


def test_extraction_mode_subagent_ok():
    errors = validate_config_dict({"extraction": {"mode": "subagent"}})
    assert errors == []


def test_extraction_mode_off_ok():
    errors = validate_config_dict({"extraction": {"mode": "off"}})
    assert errors == []


def test_extraction_mode_auto_ok():
    errors = validate_config_dict({"extraction": {"mode": "auto"}})
    assert errors == []


def test_extraction_mode_provider_ok():
    errors = validate_config_dict({"extraction": {"mode": "provider"}})
    assert errors == []


def test_extraction_mode_bogus_errors():
    errors = validate_config_dict({"extraction": {"mode": "bogus"}})
    assert any("extraction" in str(e) and "mode" in str(e) for e in errors)


def test_extraction_grace_hours_ok():
    errors = validate_config_dict({"extraction": {"grace_hours": 12}})
    assert errors == []


def test_extraction_grace_hours_negative_errors():
    errors = validate_config_dict({"extraction": {"grace_hours": -1}})
    assert any("grace_hours" in str(e) for e in errors)


def test_extraction_drain_batch_size_ok():
    errors = validate_config_dict({"extraction": {"drain_batch_size": 4}})
    assert errors == []


def test_extraction_drain_batch_size_zero_errors():
    # drain_batch_size has ge=1 in the model
    errors = validate_config_dict({"extraction": {"drain_batch_size": 0}})
    assert any("drain_batch_size" in str(e) for e in errors)


def test_extraction_drain_cooldown_seconds_ok():
    errors = validate_config_dict({"extraction": {"drain_cooldown_seconds": 60}})
    assert errors == []


def test_extraction_drain_cooldown_negative_errors():
    errors = validate_config_dict({"extraction": {"drain_cooldown_seconds": -5}})
    assert any("drain_cooldown" in str(e) for e in errors)


def test_extraction_section_is_known_top_level():
    """extraction is a known top-level section — no 'unknown section' error."""
    errors = validate_config_dict({"extraction": {"mode": "off"}})
    assert not any(
        "unknown" in str(e).lower() and "extraction" in str(e) for e in errors
    )

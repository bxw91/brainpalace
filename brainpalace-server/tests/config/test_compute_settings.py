"""Tests for compute config (Task 13, Group G5).

Compute query mode has no switches — it is always selectable and empty without
records, which are extracted whenever session extraction runs. The only compute
config knob is the confidence floor.
"""

from brainpalace_server.config.provider_config import ComputeConfig, ProviderSettings
from brainpalace_server.config.settings import Settings


def test_flat_settings_defaults():
    s = Settings()
    assert s.COMPUTE_MIN_CONFIDENCE == 0.7
    # No compute on/off switches remain.
    assert not hasattr(s, "ENABLE_COMPUTE")
    assert not hasattr(s, "RECORD_EXTRACTION_ENABLED")


def test_compute_section_all_none_by_default():
    c = ComputeConfig()
    assert c.min_confidence is None
    assert not hasattr(c, "enabled")
    assert not hasattr(c, "record_extraction")
    assert isinstance(ProviderSettings().compute, ComputeConfig)


def test_yaml_override_applies_when_env_unset(monkeypatch):
    # A set YAML key lands on Settings only when the env var is NOT explicitly
    # set (env wins). min_confidence is the only compute knob left.
    from brainpalace_server.api.main import _apply_compute_yaml_overrides
    from brainpalace_server.config import settings as s

    monkeypatch.setattr(s, "COMPUTE_MIN_CONFIDENCE", s.COMPUTE_MIN_CONFIDENCE)
    monkeypatch.delenv("COMPUTE_MIN_CONFIDENCE", raising=False)
    _apply_compute_yaml_overrides(
        ProviderSettings(compute=ComputeConfig(min_confidence=0.5))
    )
    assert s.COMPUTE_MIN_CONFIDENCE == 0.5

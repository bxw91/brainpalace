"""Tests for compute config kill-switches (Task 13, Group G5).

Mirrors the structure of tests/test_settings_overrides.py for graphrag.
"""

from brainpalace_server.config.provider_config import ComputeConfig, ProviderSettings
from brainpalace_server.config.settings import Settings


def test_flat_settings_defaults():
    s = Settings()
    assert s.RECORD_EXTRACTION_ENABLED is True
    assert s.ENABLE_COMPUTE is True
    assert s.COMPUTE_MIN_CONFIDENCE == 0.7


def test_compute_section_all_none_by_default():
    c = ComputeConfig()
    assert (c.enabled, c.record_extraction, c.min_confidence) == (None, None, None)
    assert isinstance(ProviderSettings().compute, ComputeConfig)


def test_yaml_override_applies_when_env_unset(monkeypatch):
    # mirror tests/.../test_apply_graphrag_yaml_overrides: a set YAML key lands
    # on Settings only when the env var is NOT explicitly set (env wins).
    # The override does a plain setattr on the GLOBAL settings singleton, so
    # snapshot the three fields it can mutate first: monkeypatch.setattr records
    # the pre-call value and restores it at teardown, undoing the mutation. A
    # delenv alone would leak settings.ENABLE_COMPUTE=False into later tests.
    from brainpalace_server.api.main import _apply_compute_yaml_overrides
    from brainpalace_server.config import settings as s

    for _name in (
        "ENABLE_COMPUTE",
        "RECORD_EXTRACTION_ENABLED",
        "COMPUTE_MIN_CONFIDENCE",
    ):
        monkeypatch.setattr(s, _name, getattr(s, _name))
    monkeypatch.delenv("ENABLE_COMPUTE", raising=False)
    _apply_compute_yaml_overrides(
        ProviderSettings(compute=ComputeConfig(enabled=False))
    )
    assert s.ENABLE_COMPUTE is False

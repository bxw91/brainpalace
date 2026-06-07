import pytest
import yaml

from brainpalace_dashboard.services.config_svc import (
    MASK,
    ConfigService,
    ConfigWriteError,
)


def _state(tmp_path, body):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(body)
    return state


def test_write_rejects_invalid_and_keeps_file(tmp_path):
    state = _state(tmp_path, "embedding:\n  provider: openai\n")
    svc = ConfigService()
    with pytest.raises(ConfigWriteError) as ei:
        svc.write(state, {"embedding": {"provider": "not-a-provider"}})
    assert ei.value.errors  # has field-level errors
    # original file unchanged
    assert "openai" in (state / "config.yaml").read_text()


def test_write_preserves_existing_secret_when_value_is_mask(tmp_path):
    state = _state(tmp_path, "embedding:\n  provider: openai\n  api_key: sk-REAL\n")
    svc = ConfigService()
    svc.write(state, {"embedding": {"provider": "openai", "api_key": MASK}})
    saved = yaml.safe_load((state / "config.yaml").read_text())
    # mask did not overwrite real secret
    assert saved["embedding"]["api_key"] == "sk-REAL"


def test_write_does_not_return_secret_in_clear(tmp_path):
    """Round-trip: a real secret on disk is never echoed back in clear text."""
    state = _state(tmp_path, "embedding:\n  provider: openai\n  api_key: sk-REAL\n")
    svc = ConfigService()
    # User submits the masked value (as the GET handed them); write preserves it.
    svc.write(state, {"embedding": {"provider": "openai", "api_key": MASK}})
    read_back = svc.read(state)
    assert read_back["embedding"]["api_key"] == MASK
    assert "sk-REAL" not in str(read_back)


def test_write_atomic_creates_bak(tmp_path):
    state = _state(tmp_path, "embedding:\n  provider: openai\n")
    svc = ConfigService()
    svc.write(state, {"embedding": {"provider": "ollama"}})
    assert (state / "config.yaml.bak").exists()
    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["embedding"]["provider"] == "ollama"

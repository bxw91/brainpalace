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


def test_read_write_global_roundtrip(tmp_path, monkeypatch):
    """read_global / write_global target the XDG global file and reuse the
    same validate + secret-merge + atomic-write machinery as the project path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    svc = ConfigService()
    # Absent global file reads as {}.
    assert svc.read_global() == {}
    # Write creates the XDG dir + file (and validates).
    svc.write_global({"embedding": {"provider": "ollama"}})
    read_back = svc.read_global()
    assert read_back["embedding"]["provider"] == "ollama"


def test_write_global_rejects_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    svc = ConfigService()
    with pytest.raises(ConfigWriteError):
        svc.write_global({"embedding": {"provider": "not-a-provider"}})


def test_write_global_preserves_secret_on_mask(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    svc = ConfigService()
    svc.write_global({"embedding": {"provider": "openai", "api_key": "sk-REAL"}})
    svc.write_global({"embedding": {"provider": "openai", "api_key": MASK}})
    assert svc.read_global()["embedding"]["api_key"] == MASK
    # Real secret is preserved on disk under the mask.
    raw = yaml.safe_load((tmp_path / "cfg" / "brainpalace" / "config.yaml").read_text())
    assert raw["embedding"]["api_key"] == "sk-REAL"

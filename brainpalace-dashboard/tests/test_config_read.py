from brainpalace_dashboard.services.config_svc import ConfigService


def test_read_masks_secrets(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  api_key: sk-SECRET123\n"
        "  api_key_env: OPENAI_API_KEY\n"
    )
    svc = ConfigService()
    values = svc.read(state)
    assert values["embedding"]["provider"] == "openai"
    assert values["embedding"]["api_key"] == "********"  # masked
    assert values["embedding"]["api_key_env"] == "OPENAI_API_KEY"  # not secret

from brainpalace_cli import config_schema as cs


def test_cli_dashboard_step_keys_are_canonical():
    # The keys the CLI step writes must be a subset of the validated control-plane
    # field set — prevents CLI vs Settings-tab drift (finding #1).
    cli_keys = {"autostart", "port"}  # written by _global_dashboard_settings_step
    assert cli_keys <= cs.DASHBOARD_KNOWN_FIELDS

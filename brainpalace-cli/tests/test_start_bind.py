"""Tests for the new read_bind() that reads bind config from config.yaml."""


def test_read_bind_from_yaml(tmp_path):
    from brainpalace_cli.commands.start import read_bind

    (tmp_path / "config.yaml").write_text("bind:\n  port_range_start: 9000\n")
    cfg = read_bind(tmp_path)
    assert cfg["port_range_start"] == 9000
    assert cfg["bind_host"] == "127.0.0.1"  # default


def test_read_bind_defaults_when_no_yaml(tmp_path):
    from brainpalace_cli.commands.start import read_bind

    cfg = read_bind(tmp_path)
    assert cfg["bind_host"] == "127.0.0.1"
    assert cfg["port_range_start"] == 8000
    assert cfg["port_range_end"] == 8100
    assert cfg["auto_port"] is True


def test_read_bind_global_inherit(tmp_path, monkeypatch):
    """A bind key omitted from the project config.yaml is inherited from the
    global config.yaml (project→global merge via load_bind_config / load_raw_config)."""
    from brainpalace_cli.commands.start import read_bind
    from brainpalace_cli.xdg_paths import get_xdg_config_dir

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    gdir = get_xdg_config_dir()
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "config.yaml").write_text(
        "bind:\n  bind_host: 0.0.0.0\n  port_range_start: 9000\n"
    )
    state = tmp_path / "proj" / ".brainpalace"
    state.mkdir(parents=True)
    # Project overrides only port_range_start
    (state / "config.yaml").write_text("bind:\n  port_range_start: 7000\n")

    cfg = read_bind(state)
    # project wins
    assert cfg["port_range_start"] == 7000
    # global fills in bind_host
    assert cfg["bind_host"] == "0.0.0.0"

from brainpalace_server.config.bind_config import load_bind_config


def test_bind_defaults(tmp_path):
    cfg = load_bind_config(tmp_path / "nope.yaml")
    assert cfg.bind_host == "127.0.0.1"
    assert cfg.port_range_start == 8000
    assert cfg.port_range_end == 8100
    assert cfg.auto_port is True


def test_bind_from_yaml(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("bind:\n  port_range_start: 9000\n  port_range_end: 9100\n")
    cfg = load_bind_config(p)
    assert cfg.port_range_start == 9000
    assert cfg.port_range_end == 9100

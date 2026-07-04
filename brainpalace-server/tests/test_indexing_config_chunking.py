from brainpalace_server.config.indexing_config import load_indexing_config


def test_indexing_defaults(tmp_path):
    cfg = load_indexing_config(tmp_path / "nope.yaml")
    assert cfg.skip_minified is True
    assert cfg.reembed_cooldown_seconds == 3600
    assert any("node_modules" in p for p in cfg.exclude_patterns)
    # chunk_size/overlap are no longer config keys — they are advanced per-run
    # flags on `brainpalace index`, defaulting to the built-in 512/50.
    assert not hasattr(cfg, "chunk_size")
    assert not hasattr(cfg, "chunk_overlap")


def test_indexing_overrides_from_yaml(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "indexing:\n  skip_minified: false\n  exclude_patterns:\n    - '**/foo/**'\n"
    )
    cfg = load_indexing_config(p)
    assert cfg.skip_minified is False
    # User exclude_patterns EXTEND the built-in defaults (never replace them) —
    # see load_indexing_config / commit "preserve full default exclude set".
    assert "**/foo/**" in cfg.exclude_patterns
    assert "**/node_modules/**" in cfg.exclude_patterns

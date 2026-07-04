from brainpalace_server.config.graph_indexing_config import (
    GraphIndexingConfig,
    load_graph_indexing_config,
)


def test_defaults_are_auto_and_languages_on():
    cfg = GraphIndexingConfig()
    assert cfg.lsp.mode == "auto"
    assert cfg.lsp.python is True
    assert cfg.lsp.typescript is True


def test_load_absent_block_returns_defaults(tmp_path):
    cfg = load_graph_indexing_config(tmp_path / "nope.yaml")
    assert isinstance(cfg, GraphIndexingConfig)
    assert cfg.lsp.mode == "auto"


def test_load_parses_nested_lsp_block(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "graph_indexing:\n"
        "  lsp:\n"
        "    mode: off\n"
        "    python: true\n"
        "    typescript: false\n"
    )
    cfg = load_graph_indexing_config(p)
    assert cfg.lsp.mode == "off"
    assert cfg.lsp.python is True
    assert cfg.lsp.typescript is False


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("graph_indexing:\n  bogus: 1\n  lsp:\n    mode: on\n")
    cfg = load_graph_indexing_config(p)
    assert cfg.lsp.mode == "on"

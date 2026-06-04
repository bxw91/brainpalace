from brainpalace_server.config.bm25_config import BM25Config, load_bm25_config


def test_defaults():
    c = BM25Config()
    assert c.language == "en" and c.engine == "stem" and c.detect is False
    assert c.detect_min_confidence == 0.6


def test_load_from_yaml(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("bm25:\n  language: hr\n  engine: stem\n  detect: true\n")
    c = load_bm25_config(cfg)
    assert c.language == "hr" and c.detect is True


def test_absent_block_is_defaults(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("embedding:\n  provider: openai\n")
    c = load_bm25_config(cfg)
    assert c.language == "en" and c.engine == "stem"

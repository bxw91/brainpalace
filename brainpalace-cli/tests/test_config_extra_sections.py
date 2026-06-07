"""Tests that config_schema recognizes real-world config sections.

Real config.yaml files carry sections the schema historically never modeled
(bm25, git_indexing, session_indexing, session_extraction). These must
validate cleanly, and their enum fields must still be checked.
"""

from brainpalace_cli import config_schema as cs


def test_real_world_config_validates_clean() -> None:
    cfg = {
        "embedding": {"provider": "openai", "model": "text-embedding-3-small"},
        "summarization": {"provider": "anthropic"},
        "graphrag": {"enabled": True, "store_type": "simple"},
        "bm25": {
            "language": "en",
            "engine": "stem",
            "detect": False,
            "detect_min_confidence": 0.6,
        },
        "git_indexing": {
            "enabled": False,
            "depth": 1000,
            "max_files": 50,
            "path_filter": [],
        },
        "session_indexing": {
            "enabled": True,
            "retain_days": 0,
            "window": 4,
            "stride": 2,
            "watch_debounce_ms": 30000,
            "archive": {"enabled": True},
        },
        "session_extraction": {"mode": "subagent", "quiescence_seconds": 1800},
        "reranker": {"enabled": True, "provider": "sentence-transformers"},
    }
    assert cs.validate_config_dict(cfg) == []


def test_reranker_enabled_is_known_and_typed() -> None:
    assert "enabled" in cs.RERANKER_KNOWN_FIELDS
    # bool is accepted
    assert cs.validate_config_dict({"reranker": {"enabled": False}}) == []
    # non-bool is rejected
    errs = cs.validate_config_dict({"reranker": {"enabled": "yes"}})
    assert any(e.field == "reranker.enabled" for e in errs)


def test_bad_bm25_engine_caught() -> None:
    errs = cs.validate_config_dict({"bm25": {"engine": "BOGUS"}})
    assert any(e.field == "bm25.engine" for e in errs)


def test_bad_extract_mode_caught() -> None:
    errs = cs.validate_config_dict({"session_extraction": {"mode": "BOGUS"}})
    assert any(e.field == "session_extraction.mode" for e in errs)

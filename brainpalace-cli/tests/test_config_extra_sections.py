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
        "session_extraction": {"quiescence_seconds": 1800},
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


# ---------------------------------------------------------------------------
# Phase L: indexing: block (large-file re-embed guard)
# ---------------------------------------------------------------------------


def test_indexing_block_validates_clean() -> None:
    cfg = {
        "indexing": {
            "reembed_cooldown_seconds": 3600,
            "big_file_chunks": 200,
            "max_file_bytes_throttle": 262144,
            "skip_minified": True,
        }
    }
    assert cs.validate_config_dict(cfg) == []


def test_indexing_is_known_top_level_key() -> None:
    assert "indexing" in cs.VALID_TOP_LEVEL_KEYS
    assert {
        "reembed_cooldown_seconds",
        "big_file_chunks",
        "max_file_bytes_throttle",
        "skip_minified",
    } <= cs.INDEXING_KNOWN_FIELDS


def test_indexing_unknown_field_caught() -> None:
    errs = cs.validate_config_dict({"indexing": {"bogus": 1}})
    assert any(e.field == "indexing.bogus" for e in errs)


def test_indexing_type_errors_caught() -> None:
    errs = cs.validate_config_dict(
        {"indexing": {"reembed_cooldown_seconds": "soon", "skip_minified": "yes"}}
    )
    fields = {e.field for e in errs}
    assert "indexing.reembed_cooldown_seconds" in fields
    assert "indexing.skip_minified" in fields


# ---------------------------------------------------------------------------
# compute: block (G5 — compute query mode). The wizard writes this section, so
# the CLI-side schema must recognise it; otherwise the wizard's post-write
# validation aborts on "Unknown top-level key 'compute'". Mirrors
# brainpalace_server.config.provider_config.ComputeConfig.
# ---------------------------------------------------------------------------


def test_compute_block_validates_clean() -> None:
    cfg = {"compute": {"min_confidence": 0.7}}
    assert cs.validate_config_dict(cfg) == []


def test_compute_is_known_top_level_key() -> None:
    assert "compute" in cs.VALID_TOP_LEVEL_KEYS
    # compute has no switches — only the confidence floor is configurable
    assert cs.COMPUTE_KNOWN_FIELDS == {"min_confidence"}


def test_compute_unknown_field_caught() -> None:
    errs = cs.validate_config_dict({"compute": {"bogus": 1}})
    assert any(e.field == "compute.bogus" for e in errs)
    # the removed switches are now unknown fields
    for removed in ("enabled", "record_extraction"):
        assert any(
            e.field == f"compute.{removed}"
            for e in cs.validate_config_dict({"compute": {removed: True}})
        )


def test_compute_min_confidence_out_of_range_caught() -> None:
    errs = cs.validate_config_dict({"compute": {"min_confidence": 1.5}})
    assert any(e.field == "compute.min_confidence" for e in errs)
    # An integer 1 is in range and accepted (mirrors bm25.detect_min_confidence).
    assert cs.validate_config_dict({"compute": {"min_confidence": 1}}) == []

"""Unit tests for the indexing: config block (Phase L — re-embed guard)."""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.config.indexing_config import (
    IndexingConfig,
    load_indexing_config,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_absent_block_returns_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.yaml", "embedding:\n  provider: openai\n")
    cfg = load_indexing_config(path)
    assert cfg.reembed_cooldown_seconds == 3600
    assert cfg.big_file_chunks == 200
    assert cfg.max_file_bytes_throttle == 262144
    assert cfg.skip_minified is True


def test_missing_file_returns_defaults() -> None:
    cfg = load_indexing_config(Path("/nonexistent/config.yaml"))
    assert cfg == IndexingConfig()


def test_block_overrides_parsed(tmp_path: Path) -> None:
    cfg = load_indexing_config(
        _write(
            tmp_path / "config.yaml",
            "indexing:\n"
            "  reembed_cooldown_seconds: 60\n"
            "  big_file_chunks: 10\n"
            "  max_file_bytes_throttle: 1024\n"
            "  skip_minified: false\n",
        )
    )
    assert cfg.reembed_cooldown_seconds == 60
    assert cfg.big_file_chunks == 10
    assert cfg.max_file_bytes_throttle == 1024
    assert cfg.skip_minified is False


def test_env_overrides_block(tmp_path: Path, monkeypatch) -> None:
    path = _write(
        tmp_path / "config.yaml",
        "indexing:\n  reembed_cooldown_seconds: 60\n  skip_minified: true\n",
    )
    monkeypatch.setenv("REEMBED_COOLDOWN_SECONDS", "7200")
    monkeypatch.setenv("INDEX_BIG_FILE_CHUNKS", "500")
    monkeypatch.setenv("INDEX_MAX_FILE_BYTES", "999")
    monkeypatch.setenv("INDEX_SKIP_MINIFIED", "false")
    cfg = load_indexing_config(path)
    assert cfg.reembed_cooldown_seconds == 7200
    assert cfg.big_file_chunks == 500
    assert cfg.max_file_bytes_throttle == 999
    assert cfg.skip_minified is False


def test_cooldown_zero_disables(tmp_path: Path) -> None:
    cfg = load_indexing_config(
        _write(tmp_path / "config.yaml", "indexing:\n  reembed_cooldown_seconds: 0\n")
    )
    assert cfg.reembed_cooldown_seconds == 0


def test_exclude_patterns_extend_defaults(tmp_path: Path) -> None:
    """Project exclude_patterns are ADDED to the built-in defaults, not replaced.

    Adding one file pattern must not drop node_modules/.venv/.brainpalace, else
    a user excluding CHANGELOG would silently start indexing node_modules.
    """
    defaults = IndexingConfig().exclude_patterns
    cfg = load_indexing_config(
        _write(
            tmp_path / "config.yaml",
            'indexing:\n  exclude_patterns:\n    - "**/docs/CHANGELOG.md"\n',
        )
    )
    # The new pattern is present …
    assert "**/docs/CHANGELOG.md" in cfg.exclude_patterns
    # … and every built-in default survives.
    for pat in defaults:
        assert pat in cfg.exclude_patterns
    # No duplicates introduced.
    assert len(cfg.exclude_patterns) == len(set(cfg.exclude_patterns))


def test_exclude_patterns_dedup_when_repeating_a_default(tmp_path: Path) -> None:
    """Re-listing a default pattern does not duplicate it."""
    cfg = load_indexing_config(
        _write(
            tmp_path / "config.yaml",
            'indexing:\n  exclude_patterns:\n    - "**/node_modules/**"\n',
        )
    )
    assert cfg.exclude_patterns.count("**/node_modules/**") == 1

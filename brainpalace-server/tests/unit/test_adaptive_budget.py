"""Adaptive embedding-budget cap: max(floor, ratio × index size)."""

from brainpalace_server.config.indexing_config import (
    IndexingConfig,
    load_indexing_config,
)
from brainpalace_server.services.indexing_service import effective_token_budget


def test_ratio_field_default() -> None:
    cfg = IndexingConfig()
    assert cfg.max_embed_ratio_per_job == 0.2


def test_env_override_ratio(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INDEX_MAX_EMBED_RATIO", "0.5")
    cfg = load_indexing_config(tmp_path / "missing.yaml")
    assert cfg.max_embed_ratio_per_job == 0.5


def test_effective_budget_small_index_uses_floor() -> None:
    # 100 chunks × 512 tokens = 51_200 → 20% = 10_240 < floor
    assert (
        effective_token_budget(
            floor=100_000, ratio=0.2, total_chunks=100, chunk_size=512
        )
        == 100_000
    )


def test_effective_budget_big_index_scales() -> None:
    # 20_000 chunks × 512 = 10_240_000 → 20% = 2_048_000 > floor
    assert (
        effective_token_budget(
            floor=100_000, ratio=0.2, total_chunks=20_000, chunk_size=512
        )
        == 2_048_000
    )


def test_floor_zero_disables_guard_entirely() -> None:
    assert (
        effective_token_budget(floor=0, ratio=0.2, total_chunks=20_000, chunk_size=512)
        == 0
    )


def test_ratio_zero_restores_pure_fixed_cap() -> None:
    assert (
        effective_token_budget(
            floor=100_000, ratio=0.0, total_chunks=20_000, chunk_size=512
        )
        == 100_000
    )

import pytest
from pydantic import ValidationError

from brainpalace_server.config.ranking_config import RankingConfig


def test_default_doc_weight_is_half():
    cfg = RankingConfig()
    assert cfg.doc_weight == 0.5
    assert cfg.weight_for("doc") == 0.5
    assert cfg.weight_for("code") == 1.0  # non-doc untouched
    assert cfg.weight_for("test") == 1.0


def test_doc_weight_configurable():
    assert RankingConfig(doc_weight=1.0).weight_for("doc") == 1.0
    assert RankingConfig(doc_weight=0.0).weight_for("doc") == 0.0


def test_doc_weight_bounded_0_to_1():
    with pytest.raises(ValidationError):
        RankingConfig(doc_weight=1.5)
    with pytest.raises(ValidationError):
        RankingConfig(doc_weight=-0.1)


def test_penalty_default_is_soft():
    assert RankingConfig().reference_rank_penalty == 0.7


def test_reference_rank_penalty_bounded_0_to_1():
    with pytest.raises(ValidationError):
        RankingConfig(reference_rank_penalty=1.5)
    with pytest.raises(ValidationError):
        RankingConfig(reference_rank_penalty=-0.1)

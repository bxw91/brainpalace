from brainpalace_server.config.ranking_config import RankingConfig
from brainpalace_server.services.query_service import QueryService


def test_query_service_stores_ranking_config():
    cfg = RankingConfig(doc_weight=0.5)
    qs = QueryService(ranking_config=cfg)
    assert qs.ranking_config is cfg


def test_query_service_defaults_ranking_config_none():
    qs = QueryService()
    assert getattr(qs, "ranking_config", "missing") is None

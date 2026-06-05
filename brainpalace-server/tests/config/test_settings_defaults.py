from brainpalace_server.config.settings import Settings


def test_graph_index_on_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_GRAPH_INDEX", raising=False)
    monkeypatch.delenv("GRAPH_STORE_TYPE", raising=False)
    s = Settings(_env_file=None)
    assert s.ENABLE_GRAPH_INDEX is True
    assert s.GRAPH_STORE_TYPE == "sqlite"

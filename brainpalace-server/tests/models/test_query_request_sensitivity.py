from brainpalace_server.models.query import QueryRequest


def test_include_sensitive_defaults_false():
    req = QueryRequest(query="x")
    assert req.include_sensitive is False


def test_include_sensitive_opt_in():
    req = QueryRequest(query="x", include_sensitive=True)
    assert req.include_sensitive is True

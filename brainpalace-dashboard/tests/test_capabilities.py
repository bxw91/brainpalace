from brainpalace_dashboard.services.capabilities import parse_openapi


def test_parse_openapi_flattens_paths():
    doc = {
        "paths": {
            "/health/status": {
                "get": {"summary": "Indexing Status", "tags": ["health"]}
            },
            "/query/": {"post": {"summary": "Query Documents", "tags": ["query"]}},
        }
    }
    caps = parse_openapi(doc)
    assert {
        "method": "GET",
        "path": "/health/status",
        "summary": "Indexing Status",
        "tag": "health",
    } in caps
    assert any(c["method"] == "POST" and c["path"] == "/query/" for c in caps)

import json

from brainpalace_cli.doc_sync.introspect import (
    config_dotpaths,
    dump_interface_json,
    live_snapshot,
)


def test_config_dotpaths_includes_known_keys():
    paths = set(config_dotpaths())
    assert "embedding.provider" in paths
    assert "bm25.language" in paths
    assert "server.read_only" in paths
    assert "embedding" in paths  # bare top-level key also valid


def test_live_snapshot_populates_config_and_mcp():
    snap = live_snapshot()
    assert "embedding.provider" in snap.config_keys
    assert "query" in snap.mcp_tools


def test_dump_interface_emits_config_and_mcp():
    data = json.loads(dump_interface_json())
    assert "config_keys" in data and "mcp_tools" in data


def test_endpoints_introspection_is_side_effect_free_and_lists_routes():
    # Importing the app to read routes must NOT connect/bind (lifespan deferred).
    from brainpalace_cli.doc_sync.introspect import endpoint_paths

    paths = endpoint_paths()
    assert any(p.startswith("/") for p in paths)
    assert "/health" in paths or any("health" in p for p in paths)

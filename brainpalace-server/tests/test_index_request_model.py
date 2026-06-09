"""Tests for IndexRequest.trigger field (provenance)."""

from brainpalace_server.models.index import IndexRequest


def test_index_request_trigger_defaults_to_manual():
    req = IndexRequest(folder_path="/tmp/x")
    assert req.trigger == "manual"


def test_index_request_trigger_can_be_set():
    req = IndexRequest(folder_path="/tmp/x", trigger="watch")
    assert req.trigger == "watch"

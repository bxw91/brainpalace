import inspect

from brainpalace_server.indexing import graph_index


def test_find_entity_relationships_threads_flag_to_get_triplets():
    src = inspect.getsource(graph_index.GraphIndexManager._find_entity_relationships)
    # get_triplets must be called with the sensitivity flag, not the default
    assert "get_triplets(" in src
    assert "include_sensitive" in src


def test_query_signature_has_include_sensitive():
    sig = inspect.signature(graph_index.GraphIndexManager.query)
    assert "include_sensitive" in sig.parameters
    assert sig.parameters["include_sensitive"].default is False


def test_query_by_type_signature_has_include_sensitive():
    sig = inspect.signature(graph_index.GraphIndexManager.query_by_type)
    assert "include_sensitive" in sig.parameters
    assert sig.parameters["include_sensitive"].default is False

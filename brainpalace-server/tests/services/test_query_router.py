from brainpalace_server.services.query_router import classify_compute_intent


def test_aggregation_tells_detected():
    assert classify_compute_intent("which week had the highest sales")
    assert classify_compute_intent("how many bugs did I fix")
    assert classify_compute_intent("total spend per month")


def test_plain_lookup_not_compute():
    assert not classify_compute_intent("how do I configure the embedder")
    assert not classify_compute_intent("show me the auth middleware")

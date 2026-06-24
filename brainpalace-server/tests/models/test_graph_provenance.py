from brainpalace_server.models.graph import GraphEntity, GraphTriple


def test_entity_defaults_domain_and_provenance():
    e = GraphEntity(name="Foo", entity_type="Class")
    assert e.domain == "code" and e.source is None and e.confidence == 0.0


def test_triple_accepts_provenance():
    t = GraphTriple(
        subject="A",
        predicate="calls",
        object="B",
        domain="chat-life",
        source="session",
        confidence=1.0,
    )
    assert t.domain == "chat-life" and t.confidence == 1.0

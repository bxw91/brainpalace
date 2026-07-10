from brainpalace_server.models.graph import GraphEntity, GraphTriple


def test_entity_sensitivity_defaults_normal():
    assert GraphEntity(name="Foo", entity_type="Class").sensitivity == "normal"


def test_entity_sensitivity_open_string():
    e = GraphEntity(name="Foo", entity_type="Class", sensitivity="private")
    assert e.sensitivity == "private"


def test_triple_sensitivity_defaults_normal():
    t = GraphTriple(subject="Foo", predicate="uses", object="Bar")
    assert t.sensitivity == "normal"


def test_triple_sensitivity_open_string():
    t = GraphTriple(
        subject="Foo", predicate="uses", object="Bar", sensitivity="private"
    )
    assert t.sensitivity == "private"

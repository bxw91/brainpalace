from brainpalace_server.models.graph import GraphTriple


def test_effective_ids_fall_back_to_subject_object():
    t = GraphTriple(subject="foo", predicate="calls", object="bar")
    assert t.effective_subject_id == "foo"
    assert t.effective_object_id == "bar"


def test_explicit_ids_and_display_names():
    t = GraphTriple(
        subject="foo",
        predicate="contains",
        object="bar",
        subject_id="f.py:foo",
        object_id="f.py:bar",
        subject_name="foo",
        object_name="bar",
        source_file="f.py",
    )
    assert t.effective_subject_id == "f.py:foo"
    assert t.effective_object_id == "f.py:bar"
    assert t.subject_name == "foo"
    assert t.source_file == "f.py"

from brainpalace_server.indexing.text_analysis.code import CodeAnalyzer


def test_no_stemming_no_identifier_split():
    a = CodeAnalyzer()
    # identifier stays whole; no camelCase split, no stemming
    assert a.analyze("getUserById") == ["getuserbyid"]


def test_splits_on_nonword_only():
    a = CodeAnalyzer()
    assert a.analyze("foo.bar(baz)") == ["foo", "bar", "baz"]


def test_no_nl_stopwords_removed():
    a = CodeAnalyzer()
    assert a.analyze("the and is") == ["the", "and", "is"]  # code keeps them

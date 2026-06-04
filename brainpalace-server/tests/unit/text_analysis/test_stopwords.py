from brainpalace_server.indexing.text_analysis.stopwords import stopwords_for


def test_known_language_has_stopwords():
    en = stopwords_for("en")
    assert "the" in en and "and" in en


def test_croatian_stopwords_present():
    hr = stopwords_for("hr")
    assert {"i", "je", "na", "u"} <= hr


def test_unknown_language_returns_empty_frozenset():
    assert stopwords_for("xx") == frozenset()


def test_result_is_cached_same_object():
    assert stopwords_for("en") is stopwords_for("en")

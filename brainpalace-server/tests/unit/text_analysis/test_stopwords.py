import pytest

from brainpalace_server.indexing.text_analysis.stopwords import (
    _load_stopword_data,
    stopwords_for,
)


def test_vendored_stopword_data_loads():
    data = _load_stopword_data()
    assert "en" in data
    assert "the" in data["en"]


def test_vendored_matches_stopwordsiso():
    """Parity guard: vendored data must equal the upstream stopwordsiso source.

    Skipped once stopwordsiso is uninstalled; runs while the dep is still present
    to prove the one-time copy is faithful across all languages.
    """
    stopwordsiso = pytest.importorskip("stopwordsiso")
    from brainpalace_server.indexing.text_analysis.base import normalize

    for code in stopwordsiso.langs():
        if not stopwordsiso.has_lang(code):
            continue
        expected = frozenset(normalize(w) for w in stopwordsiso.stopwords(code))
        assert stopwords_for(code) == expected, f"mismatch for {code}"


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

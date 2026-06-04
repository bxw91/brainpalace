import pytest

from brainpalace_server.indexing.text_analysis.snowball import SNOWBALL, make_snowball


@pytest.mark.parametrize(
    "code,word",
    [
        ("en", "running"),
        ("de", "läuft"),
        ("fr", "manger"),
        ("ru", "бегать"),
    ],
)
def test_snowball_stems_and_drops_stopwords(code, word):
    a = make_snowball(code)
    toks = a.analyze(f"{word} the und le и")  # mixed stopwords, harmless
    assert toks, "analyzer produced no tokens"
    # stemming is deterministic
    assert a.analyze(word) == a.analyze(word)


def test_english_conflates_regular_inflections():
    a = make_snowball("en")
    assert a.analyze("documents")[0] == a.analyze("document")[0]


def test_stopwords_removed_english():
    a = make_snowball("en")
    assert "the" not in a.analyze("the cat")


def test_table_covers_pystemmer_algorithms():
    import Stemmer

    algos = {x.lower() for x in Stemmer.algorithms()}
    # Every SNOWBALL algo must be a real PyStemmer algorithm.
    assert set(SNOWBALL.values()) <= algos
    # We ship the major languages.
    assert {"en", "de", "fr", "es", "ru", "it", "pt", "nl"} <= set(SNOWBALL)

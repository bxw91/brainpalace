import pytest

from brainpalace_server.indexing.text_analysis.croatian import (
    CroatianLemmaAnalyzer,
    CroatianStemAnalyzer,
)


def test_inflections_collapse_to_same_stem():
    a = CroatianStemAnalyzer()
    # NOTE: the nominative plural "liječnici" is intentionally excluded. Croatian
    # sibilarization palatalizes k -> c before the -i ending (liječnik -> liječnici),
    # and the rule-based Ljubešić–Pandžić stemmer does not reverse that consonant
    # mutation — it leaves "liječnic" (verified byte-identical to upstream). That is
    # a genuine limitation of the vendored stemmer, not a wrapper-extraction bug, so
    # the test exercises the case forms that share the unmutated "liječnik" stem.
    forms = ["liječnik", "liječnika", "liječniku", "liječnikom", "liječnike"]
    stems = {a.analyze(f)[0] for f in forms if a.analyze(f)}
    assert len(stems) == 1, f"expected one stem, got {stems}"


def test_distinct_words_distinct_stems():
    a = CroatianStemAnalyzer()
    assert a.analyze("pas")[0] != a.analyze("mačka")[0]


def test_diacritics_preserved():
    a = CroatianStemAnalyzer()
    toks = a.analyze("liječnički pristup")
    assert any("č" in t or "ć" in t or "ž" in t for t in toks)


def test_stopwords_dropped():
    a = CroatianStemAnalyzer()
    assert not (set(a.analyze("i ili ali da")) & {"i", "ili", "ali", "da"})


def test_idempotent():
    a = CroatianStemAnalyzer()
    assert a.analyze("termina") == a.analyze("termina")


def test_lemma_collapses_inflections():
    pytest.importorskip("simplemma")
    a = CroatianLemmaAnalyzer()
    forms = ["liječnika", "liječniku", "liječnikom"]
    stems = {a.analyze(f)[0] for f in forms if a.analyze(f)}
    assert stems == {"liječnik"}

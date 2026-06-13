from brainpalace_server.indexing.text_analysis.registry import (
    LEMMA_LANGUAGES,
    get_analyzer,
    lemma_language_label,
    lemma_languages,
)
from brainpalace_server.indexing.text_analysis.snowball import SNOWBALL


def test_all_snowball_codes_resolve_and_work():
    for code in SNOWBALL:
        a = get_analyzer(code, "stem")
        assert a.analyze("test riječ word") is not None


def test_croatian_stem_default():
    assert get_analyzer("hr", "stem").name == "Croatian"


def test_code_ignores_engine():
    assert get_analyzer("code", "stem").name == "Code"
    assert get_analyzer("code", "anything").name == "Code"


def test_unknown_language_falls_back_to_english():
    a = get_analyzer("zz", "stem")
    assert a.code == "en"


def test_cached_singleton():
    assert get_analyzer("hr", "stem") is get_analyzer("hr", "stem")


def test_lemma_engine_selects_lemma_analyzer():
    a = get_analyzer("hr", "lemma")
    assert a.name == "Croatian (lemma)"  # does not load model until analyze_batch


def test_lemma_languages_lists_only_lemma_capable_codes():
    # Every advertised code must actually resolve to a lemma analyzer (not the
    # stem fallback) — the CLI prompt promises lemma support for exactly these.
    assert LEMMA_LANGUAGES, "expected at least one lemma language"
    for code in LEMMA_LANGUAGES:
        assert "lemma" in get_analyzer(code, "lemma").name.lower()
    # Stem-only Snowball langs and the English fallback are NOT advertised.
    assert "en" not in LEMMA_LANGUAGES
    assert lemma_languages() == LEMMA_LANGUAGES
    assert lemma_languages() is not LEMMA_LANGUAGES  # returns a copy


def test_lemma_language_label_joins_human_names():
    label = lemma_language_label()
    assert label  # non-empty
    for human in LEMMA_LANGUAGES.values():
        assert human in label

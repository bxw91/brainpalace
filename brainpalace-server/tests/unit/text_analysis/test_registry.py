from brainpalace_server.indexing.text_analysis.registry import get_analyzer
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

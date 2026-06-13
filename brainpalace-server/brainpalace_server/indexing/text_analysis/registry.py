from __future__ import annotations

from functools import cache

from brainpalace_server.indexing.text_analysis.base import TextAnalyzer
from brainpalace_server.indexing.text_analysis.code import CodeAnalyzer
from brainpalace_server.indexing.text_analysis.croatian import (
    CroatianLemmaAnalyzer,
    CroatianStemAnalyzer,
)
from brainpalace_server.indexing.text_analysis.snowball import SNOWBALL, make_snowball

# Single source of truth: languages that have a dedicated lemma (lemmatization)
# analyzer. Stem-only Snowball languages and the English fallback are NOT here —
# the lemma BM25 engine only helps where we actually ship a lemmatizer. The CLI
# wizards read this (via `lemma_languages` / `lemma_language_label`) so the
# "inflected languages" prompt lists exactly what lemma supports, with no
# duplicated/hardcoded list to drift. Keep in sync with `get_analyzer` dispatch.
LEMMA_LANGUAGES: dict[str, str] = {"hr": "Croatian/Serbian"}


def lemma_languages() -> dict[str, str]:
    """Map of ISO code -> human label for every lemma-capable language."""
    return dict(LEMMA_LANGUAGES)


def lemma_language_label() -> str:
    """Comma-joined human labels of lemma-capable languages (for prompts/docs)."""
    return ", ".join(LEMMA_LANGUAGES.values())


@cache
def get_analyzer(code: str, engine: str = "stem") -> TextAnalyzer:
    if code == "code":
        return CodeAnalyzer()
    if code in LEMMA_LANGUAGES:
        # Currently only `hr` ships a stem+lemma analyzer pair.
        return CroatianLemmaAnalyzer() if engine == "lemma" else CroatianStemAnalyzer()
    if code in SNOWBALL:
        return make_snowball(code)  # snowball langs are stemmer-only
    return make_snowball("en")  # safe fallback for unregistered codes

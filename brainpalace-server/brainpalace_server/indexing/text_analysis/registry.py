from __future__ import annotations

from functools import cache

from brainpalace_server.indexing.text_analysis.base import TextAnalyzer
from brainpalace_server.indexing.text_analysis.code import CodeAnalyzer
from brainpalace_server.indexing.text_analysis.croatian import (
    CroatianLemmaAnalyzer,
    CroatianStemAnalyzer,
)
from brainpalace_server.indexing.text_analysis.snowball import SNOWBALL, make_snowball


@cache
def get_analyzer(code: str, engine: str = "stem") -> TextAnalyzer:
    if code == "code":
        return CodeAnalyzer()
    if code == "hr":
        return CroatianLemmaAnalyzer() if engine == "lemma" else CroatianStemAnalyzer()
    if code in SNOWBALL:
        return make_snowball(code)  # snowball langs are stemmer-only
    return make_snowball("en")  # safe fallback for unregistered codes

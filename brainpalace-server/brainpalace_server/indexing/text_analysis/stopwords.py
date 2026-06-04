"""Stopword sets per ISO 639-1 code, sourced from stopwordsiso (~57 languages,
includes hr). Languages absent from the dataset return an empty set (stemmer-only)."""

from __future__ import annotations

from functools import cache

import stopwordsiso

from brainpalace_server.indexing.text_analysis.base import normalize


@cache
def stopwords_for(code: str) -> frozenset[str]:
    if not stopwordsiso.has_lang(code):
        return frozenset()
    # Normalize stopwords through the SAME normalize() used on tokens, so
    # comparison is apples-to-apples (NFC + lowercase).
    return frozenset(normalize(w) for w in stopwordsiso.stopwords(code))

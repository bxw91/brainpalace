"""Stopword sets per ISO 639-1 code, sourced from the stopwords-iso dataset
(~57 languages, includes hr). Languages absent from the dataset return an empty
set (stemmer-only).

The dataset JSON is vendored under ``vendor/stopwords-iso.json`` and loaded with
the stdlib ``importlib.resources`` — no runtime dependency on ``stopwordsiso``
(which hard-imports the removed ``pkg_resources``, crashing on setuptools >= 81)."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files

from brainpalace_server.indexing.text_analysis.base import normalize

_DATA_PACKAGE = "brainpalace_server.indexing.text_analysis.vendor"
_DATA_FILE = "stopwords-iso.json"


@cache
def _load_stopword_data() -> dict[str, list[str]]:
    raw = (files(_DATA_PACKAGE) / _DATA_FILE).read_text(encoding="utf-8")
    data: dict[str, list[str]] = json.loads(raw)
    return data


@cache
def stopwords_for(code: str) -> frozenset[str]:
    words = _load_stopword_data().get(code)
    if not words:
        return frozenset()
    # Normalize stopwords through the SAME normalize() used on tokens, so
    # comparison is apples-to-apples (NFC + lowercase).
    return frozenset(normalize(w) for w in words)

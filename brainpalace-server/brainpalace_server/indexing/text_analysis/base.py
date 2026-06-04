"""Per-language text analysis for BM25.

The TextAnalyzer.analyze method is the single source of truth used by BOTH
index and query paths, guaranteeing symmetry.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Protocol, runtime_checkable

#: Unicode word tokenizer. \w+ keeps letters incl. č ć š ž đ; never ASCII-folds.
TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def normalize(text: str) -> str:
    """NFC normalize + lowercase. Preserves diacritics (no ASCII folding)."""
    return unicodedata.normalize("NFC", text).lower()


@runtime_checkable
class TextAnalyzer(Protocol):
    code: str  # ISO 639-1, e.g. "hr", "en"
    name: str

    def normalize(self, text: str) -> str: ...

    def analyze(self, text: str) -> list[str]:
        """Full pipeline -> BM25 tokens.

        normalize -> tokenize -> stopwords -> conflate (stem/lemmatize).
        """
        ...

    def analyze_batch(self, texts: list[str]) -> list[list[str]]:
        """Default loops analyze(); heavy analyzers override to batch."""
        ...

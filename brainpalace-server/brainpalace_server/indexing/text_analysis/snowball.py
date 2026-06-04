"""One parametrized analyzer covering every PyStemmer/Snowball language."""

from __future__ import annotations

import Stemmer

from brainpalace_server.indexing.text_analysis.base import TOKEN_RE, normalize
from brainpalace_server.indexing.text_analysis.stopwords import stopwords_for

#: ISO 639-1 code -> PyStemmer algorithm name. Every value MUST be in
#: Stemmer.algorithms() (asserted by test). Croatian is intentionally absent
#: (no Snowball Croatian — handled by croatian.py).
SNOWBALL: dict[str, str] = {
    "ar": "arabic",
    "eu": "basque",
    "ca": "catalan",
    "da": "danish",
    "nl": "dutch",
    "en": "english",
    "fi": "finnish",
    "fr": "french",
    "de": "german",
    "el": "greek",
    "hi": "hindi",
    "hu": "hungarian",
    "id": "indonesian",
    "ga": "irish",
    "it": "italian",
    "lt": "lithuanian",
    "ne": "nepali",
    "no": "norwegian",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sr": "serbian",
    "es": "spanish",
    "sv": "swedish",
    "ta": "tamil",
    "tr": "turkish",
    "hy": "armenian",
}
# Note: 'porter' and 'yiddish' PyStemmer algos are omitted (no ISO-1 / niche).


class SnowballAnalyzer:
    def __init__(self, code: str, algo: str):
        self.code = code
        self.name = algo.capitalize()
        self._stem = Stemmer.Stemmer(algo).stemWord
        self._stop = stopwords_for(code)

    def normalize(self, text: str) -> str:
        return normalize(text)

    def analyze(self, text: str) -> list[str]:
        toks = TOKEN_RE.findall(self.normalize(text))
        return [self._stem(t) for t in toks if t not in self._stop]

    def analyze_batch(self, texts: list[str]) -> list[list[str]]:
        return [self.analyze(t) for t in texts]


def make_snowball(code: str) -> SnowballAnalyzer:
    return SnowballAnalyzer(code, SNOWBALL[code])

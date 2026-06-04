"""Croatian analyzers. Default = vendored Ljubešić–Pandžić rule-based stemmer
(no Snowball Croatian exists). Optional lemma engine uses simplemma
(Serbo-Croatian ``hbs`` data), opt-in via ``pip install 'brainpalace[lemma-hr]'``."""

from __future__ import annotations

from typing import Any

from brainpalace_server.indexing.text_analysis.base import TOKEN_RE, normalize
from brainpalace_server.indexing.text_analysis.stopwords import stopwords_for
from brainpalace_server.indexing.text_analysis.vendor.croatian_stemmer import stem_word


class CroatianStemAnalyzer:
    code = "hr"
    name = "Croatian"

    def __init__(self) -> None:
        self._stop = stopwords_for("hr")

    def normalize(self, text: str) -> str:
        return normalize(text)

    def analyze(self, text: str) -> list[str]:
        toks = TOKEN_RE.findall(self.normalize(text))
        return [stem_word(t) for t in toks if t not in self._stop]

    def analyze_batch(self, texts: list[str]) -> list[list[str]]:
        return [self.analyze(t) for t in texts]


class CroatianLemmaAnalyzer:
    """Opt-in high-accuracy tier. Uses ``simplemma`` (Serbo-Croatian ``hbs``
    data, which covers Croatian) for per-token lemmatization. Install via
    ``pip install 'brainpalace[lemma-hr]'``. simplemma is lazy-imported on first
    use, so importing this module stays cheap and a missing dependency yields a
    clear, actionable error instead of an import-time crash."""

    code = "hr"
    name = "Croatian (lemma)"

    def __init__(self) -> None:
        self._stop = stopwords_for("hr")

    def _simplemma(self) -> Any:
        try:
            import simplemma
        except ImportError as e:
            raise RuntimeError(
                "engine=lemma for 'hr' needs simplemma. Install with "
                "`pip install 'brainpalace[lemma-hr]'` or set bm25.engine=stem."
            ) from e
        return simplemma

    def normalize(self, text: str) -> str:
        return normalize(text)

    def analyze(self, text: str) -> list[str]:
        simplemma = self._simplemma()
        toks = TOKEN_RE.findall(self.normalize(text))
        out: list[str] = []
        for tok in toks:
            if tok in self._stop:
                continue
            lemma = normalize(simplemma.lemmatize(tok, lang="hbs"))
            if lemma and lemma not in self._stop:
                out.append(lemma)
        return out

    def analyze_batch(self, texts: list[str]) -> list[list[str]]:
        return [self.analyze(t) for t in texts]

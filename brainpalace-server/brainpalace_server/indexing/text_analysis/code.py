"""Analyzer for code chunks. Deliberately minimal: reproduces today's code-search
tokenization (normalize + \\w+). No stemming, no NL stopwords, no identifier
splitting (that is a separate future feature — see spec Out-of-scope)."""

from __future__ import annotations

from brainpalace_server.indexing.text_analysis.base import TOKEN_RE, normalize


class CodeAnalyzer:
    code = "code"
    name = "Code"

    def normalize(self, text: str) -> str:
        return normalize(text)

    def analyze(self, text: str) -> list[str]:
        return TOKEN_RE.findall(self.normalize(text))

    def analyze_batch(self, texts: list[str]) -> list[list[str]]:
        return [self.analyze(t) for t in texts]

"""Pure-Python language detection (py3langid), constrained to a language set."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py3langid.langid import LanguageIdentifier


@lru_cache(maxsize=1)
def _identifier(allowed: tuple[str, ...]) -> LanguageIdentifier:
    from py3langid.langid import MODEL_FILE, LanguageIdentifier

    ident = LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)
    if allowed:
        ident.set_languages(list(allowed))
    return ident


def detect_language(
    text: str,
    allowed: set[str],
    default: str,
    min_confidence: float = 0.6,
) -> str:
    """Detect the language of *text*, constrained to *allowed* language codes.

    Returns the detected ISO 639-1 code when the classifier confidence is at
    least *min_confidence* and the code is in *allowed*; otherwise returns
    *default*.

    The underlying py3langid model is loaded once and cached.  The *allowed*
    set is converted to a sorted tuple so that identical sets always map to the
    same cache entry regardless of iteration order.
    """
    if not text.strip():
        return default
    code, prob = _identifier(tuple(sorted(allowed))).classify(text)
    return code if (code in allowed and prob >= min_confidence) else default

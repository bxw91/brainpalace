"""Text analysis package for multi-language BM25 support."""

from brainpalace_server.indexing.text_analysis.base import TextAnalyzer, normalize

__all__ = ["TextAnalyzer", "normalize", "get_analyzer"]


def get_analyzer(code: str, engine: str = "stem") -> "TextAnalyzer":
    """Return the TextAnalyzer for *code* (ISO 639-1) using *engine*.

    Imported lazily to avoid import cycles; the real registry is built in
    Task 6. Calling this before registry.py exists raises ImportError.
    """
    # Lazy import: registry.py does not exist yet (built in Task 6).
    from brainpalace_server.indexing.text_analysis.registry import (  # noqa: PLC0415
        get_analyzer as _g,
    )

    return _g(code, engine)

"""Task 4c: model→window map + window-derived chunk sizing."""

from brainpalace_server.config.model_windows import resolve_chunk_chars, window_for


def _rcw(**k: object) -> int:
    return resolve_chunk_chars(provider="x", model="y", **k)  # type: ignore[arg-type]


def test_resolve_chunk_chars():
    assert (
        _rcw(provider_context_tokens=0, distill_chunk_chars=0) == 16000
    )  # unknown → floor
    assert (
        _rcw(provider_context_tokens=8192, distill_chunk_chars=0) == 16000
    )  # 8k → floor
    assert (
        _rcw(provider_context_tokens=200000, distill_chunk_chars=0) > 200000
    )  # big window
    assert (
        _rcw(provider_context_tokens=200000, distill_chunk_chars=30000) == 30000
    )  # explicit wins


def test_window_for_offered_models():
    assert window_for("openai", "gpt-4o") == 128000
    assert window_for("anthropic", "claude-3-5-sonnet") == 200000
    assert window_for("openai", "unknown-model") is None

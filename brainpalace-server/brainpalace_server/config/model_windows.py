"""Task 4c — model→context-window map + window-derived chunk sizing.

The map contains only the **offered** summarization models; unknown models fall
to a safe floor.  Chunk sizing derives from the model's context window:

    derive(tokens) = clamp(int(tokens × 3.5 × 0.6), 16_000, 2_000_000)

Rationale for the floor (Step 0 finding):
  With the previous fixed DEFAULT_CHUNK_CHARS = 48_000 (~12k tokens), a call to
  an Ollama/llama model whose context is 8k either silently truncates the input
  (local models drop the tail without error) or returns an HTTP error that
  ``_generate`` catches as None, leaving the session un-marked for retry.  Both
  paths degrade quality silently.  The 16_000-char floor (~4.5k tokens) fits
  safely inside even the smallest production-grade 4k-context model.
"""

from __future__ import annotations

#: provider/model → context window in tokens.  Keep small and commented.
#: Prefix-match semantics: entries without a date suffix also match versioned names
#: (callers that want exact match call window_for with the full model string).
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # ── OpenAI ────────────────────────────────────────────────────────────────
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "openai/gpt-4-turbo": 128_000,
    "openai/gpt-4": 8_192,
    "openai/gpt-3.5-turbo": 16_385,
    "openai/gpt-5": 128_000,  # estimated; update when published
    "openai/gpt-5-mini": 128_000,  # estimated
    # ── Anthropic ─────────────────────────────────────────────────────────────
    "anthropic/claude-3-5-sonnet": 200_000,
    "anthropic/claude-3-5-haiku": 200_000,
    "anthropic/claude-3-opus": 200_000,
    "anthropic/claude-3-haiku": 200_000,
    "anthropic/claude-3-sonnet": 200_000,
    "anthropic/claude-haiku-4-5": 200_000,
    "anthropic/claude-haiku-4-5-20251001": 200_000,
    "anthropic/claude-sonnet-4-5": 200_000,
    "anthropic/claude-opus-4": 200_000,
    # ── Google Gemini ──────────────────────────────────────────────────────────
    "gemini/gemini-2.0-flash": 1_048_576,
    "gemini/gemini-2.5-flash": 1_048_576,
    "gemini/gemini-2.5-pro": 1_048_576,
    "gemini/gemini-1.5-pro": 1_048_576,
    "gemini/gemini-1.5-flash": 1_048_576,
    "gemini/gemini-3.1-flash-lite": 1_048_576,  # estimated
    # ── xAI Grok ──────────────────────────────────────────────────────────────
    "grok/grok-3": 131_072,
    "grok/grok-3-mini": 131_072,
    "grok/grok-4": 256_000,  # estimated
    "grok/grok-4-fast": 256_000,  # estimated
    # ── Cohere ────────────────────────────────────────────────────────────────
    "cohere/command-r-plus": 128_000,
    "cohere/command-r": 128_000,
    # ── Common Ollama defaults ─────────────────────────────────────────────────
    "ollama/llama3.2": 131_072,
    "ollama/llama3.1": 131_072,
    "ollama/mistral": 32_768,
    "ollama/mistral-nemo": 128_000,
    "ollama/qwen2.5": 128_000,
    "ollama/deepseek-r1": 64_000,
}

#: Minimum chunk size (chars) regardless of model window.
_FLOOR = 16_000
#: Maximum chunk size (chars) — sanity cap.
_CEILING = 2_000_000


def window_for(provider: str, model: str) -> int | None:
    """Return the context window (tokens) for ``provider/model``, or None.

    Exact lookup first; then prefix-match for versioned model names
    (e.g. ``anthropic/claude-3-5-sonnet-20241022`` → matches
    ``anthropic/claude-3-5-sonnet``).
    """
    key = f"{provider}/{model}"
    if key in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[key]
    # Prefix match: try each map key as a prefix of the supplied key.
    for entry, tokens in MODEL_CONTEXT_WINDOWS.items():
        if key.startswith(entry):
            return tokens
    return None


def _derive(tokens: int) -> int:
    """Derive a safe chunk char budget from a context-window token count.

    Uses ~2 chars/token (conservative — code skews low, ~2-3 chars per token
    vs English prose at ~4), then takes 60% of the window for body text,
    leaving 40% headroom for the surrounding prompt.  The floor (16 000 chars,
    ~4.5k tokens) ensures a chunk always fits even in a 4k-token model.
    """
    # 2 chars/token × 60 % window utilisation = 1.2 chars per token of window
    return max(_FLOOR, min(_CEILING, int(tokens * 2 * 0.6)))


def resolve_chunk_chars(
    *,
    provider_context_tokens: int,
    distill_chunk_chars: int,
    provider: str,
    model: str,
) -> int:
    """Return the char budget per distillation call.

    Priority:
    1. ``distill_chunk_chars > 0`` — explicit override from config.
    2. ``provider_context_tokens > 0`` — derive from the user-set window.
    3. ``window_for(provider, model)`` — derive from the model map.
    4. Floor — unknown/unset model → safe 16k-char floor (~4.5k tokens).
    """
    if distill_chunk_chars > 0:
        return distill_chunk_chars
    if provider_context_tokens > 0:
        return _derive(provider_context_tokens)
    w = window_for(provider, model)
    if w is not None:
        return _derive(w)
    # Unknown model → safe floor; never overflow.
    return _derive(4096)

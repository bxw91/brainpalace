"""Tests for Usage dataclass + *_with_usage sibling methods on all providers.

Step 1 from Task 2: base defaults + anthropic mapping.
Step 6 tests: one per remaining provider (openai/grok/gemini/ollama summ;
              openai/cohere/ollama emb).

Divergences from plan table (real code takes precedence):
- Ollama summarization uses AsyncOpenAI (OpenAI-compat), so usage fields are
  prompt_tokens/completion_tokens, not prompt_eval_count/eval_count.
- Ollama embedding uses AsyncOpenAI (OpenAI-compat), so usage field is
  prompt_tokens, not prompt_eval_count.
"""

import pytest

from brainpalace_server.providers.base import BaseSummarizationProvider, Usage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Dummy(BaseSummarizationProvider):
    provider_name = "Dummy"  # type: ignore[assignment]

    async def generate(self, prompt: str) -> str:
        return "ok"


# ---------------------------------------------------------------------------
# Base defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_generate_with_usage_defaults_zero():
    p = _Dummy(model="m")
    text, usage = await p.generate_with_usage("hi")
    assert text == "ok"
    assert usage == Usage()  # zeros — truthful for providers that don't report


# ---------------------------------------------------------------------------
# Anthropic summarization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_maps_response_usage(monkeypatch):
    from brainpalace_server.providers.summarization import anthropic as a

    class _U:  # mimic anthropic SDK usage block
        input_tokens, output_tokens = 100, 20
        cache_read_input_tokens, cache_creation_input_tokens = 40, 5

    class _Resp:
        content = [type("C", (), {"text": "hello"})]
        usage = _U()

    class _Msgs:
        async def create(self, **k):
            return _Resp()

    prov = a.AnthropicSummarizationProvider.__new__(a.AnthropicSummarizationProvider)
    prov._model, prov._max_tokens, prov._temperature = "m", 10, 0.0
    prov._client = type("Cl", (), {"messages": _Msgs()})()
    text, usage = await prov.generate_with_usage("hi")
    assert text == "hello"
    assert usage == Usage(tokens_in=100, tokens_out=20, cache_read=40, cache_write=5)


# ---------------------------------------------------------------------------
# OpenAI summarization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_summarization_maps_response_usage(monkeypatch):
    from brainpalace_server.providers.summarization import openai as o

    class _PtDetails:
        cached_tokens = 30

    class _U:
        prompt_tokens = 80
        completion_tokens = 15
        prompt_tokens_details = _PtDetails()

    class _Msg:
        content = "world"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = _U()

    class _Completions:
        async def create(self, **k):
            return _Resp()

    class _Chat:
        completions = _Completions()

    prov = o.OpenAISummarizationProvider.__new__(o.OpenAISummarizationProvider)
    prov._model, prov._max_tokens, prov._temperature = "m", 10, 0.0
    prov._client = type("Cl", (), {"chat": _Chat()})()
    text, usage = await prov.generate_with_usage("hi")
    assert text == "world"
    assert usage == Usage(tokens_in=80, tokens_out=15, cache_read=30, cache_write=0)


# ---------------------------------------------------------------------------
# Grok summarization (OpenAI-compat — same shape as OpenAI, no cache fields)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grok_summarization_maps_response_usage(monkeypatch):
    from brainpalace_server.providers.summarization import grok as g

    class _U:
        prompt_tokens = 60
        completion_tokens = 12

    class _Msg:
        content = "grok-answer"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = _U()

    class _Completions:
        async def create(self, **k):
            return _Resp()

    class _Chat:
        completions = _Completions()

    prov = g.GrokSummarizationProvider.__new__(g.GrokSummarizationProvider)
    prov._model, prov._max_tokens, prov._temperature = "m", 10, 0.0
    prov._client = type("Cl", (), {"chat": _Chat()})()
    text, usage = await prov.generate_with_usage("hi")
    assert text == "grok-answer"
    assert usage == Usage(tokens_in=60, tokens_out=12, cache_read=0, cache_write=0)


# ---------------------------------------------------------------------------
# Gemini summarization
# Note: response attribute is usage_metadata (snake_case confirmed from SDK).
# Fields: prompt_token_count / candidates_token_count / cached_content_token_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_summarization_maps_response_usage(monkeypatch):
    from brainpalace_server.providers.summarization import gemini as gm

    class _UM:
        prompt_token_count = 70
        candidates_token_count = 18
        cached_content_token_count = 25

    class _Resp:
        text = "gemini-answer"
        usage_metadata = _UM()

    class _Models:
        async def generate_content(self, **k):
            return _Resp()

    class _Aio:
        models = _Models()

    prov = gm.GeminiSummarizationProvider.__new__(gm.GeminiSummarizationProvider)
    prov._model, prov._max_tokens, prov._temperature = "m", 10, 0.0
    prov._generation_config = None
    prov._client = type("Cl", (), {"aio": _Aio()})()
    text, usage = await prov.generate_with_usage("hi")
    assert text == "gemini-answer"
    assert usage == Usage(tokens_in=70, tokens_out=18, cache_read=25, cache_write=0)


# ---------------------------------------------------------------------------
# Ollama summarization
# DIVERGENCE from plan: uses AsyncOpenAI (OpenAI-compat) — response has
# usage.prompt_tokens / usage.completion_tokens, NOT prompt_eval_count/eval_count.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_summarization_maps_response_usage(monkeypatch):
    from brainpalace_server.providers.summarization import ollama as ol

    class _U:
        prompt_tokens = 55
        completion_tokens = 11

    class _Msg:
        content = "ollama-answer"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = _U()

    class _Completions:
        async def create(self, **k):
            return _Resp()

    class _Chat:
        completions = _Completions()

    prov = ol.OllamaSummarizationProvider.__new__(ol.OllamaSummarizationProvider)
    prov._model, prov._max_tokens, prov._temperature = "m", 10, 0.0
    prov._base_url = "http://localhost:11434/v1"
    prov._client = type("Cl", (), {"chat": _Chat()})()
    text, usage = await prov.generate_with_usage("hi")
    assert text == "ollama-answer"
    assert usage == Usage(tokens_in=55, tokens_out=11, cache_read=0, cache_write=0)


# ---------------------------------------------------------------------------
# OpenAI embedding
# Fields: usage.prompt_tokens / usage.prompt_tokens_details.cached_tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_embedding_maps_batch_usage(monkeypatch):
    from brainpalace_server.providers.embedding import openai as oe

    class _PtDetails:
        cached_tokens = 10

    class _U:
        prompt_tokens = 50
        prompt_tokens_details = _PtDetails()

    class _Item:
        def __init__(self, emb):
            self.embedding = emb

    class _Resp:
        data = [_Item([0.1, 0.2]), _Item([0.3, 0.4])]
        usage = _U()

    class _Embeddings:
        async def create(self, **k):
            return _Resp()

    prov = oe.OpenAIEmbeddingProvider.__new__(oe.OpenAIEmbeddingProvider)
    prov._model = "text-embedding-3-large"
    prov._batch_size = 100
    prov._dimensions_override = None
    prov._client = type("Cl", (), {"embeddings": _Embeddings()})()
    embs, usage = await prov._embed_batch_with_usage(["a", "b"])
    assert embs == [[0.1, 0.2], [0.3, 0.4]]
    assert usage == Usage(tokens_in=50, tokens_out=0, cache_read=10, cache_write=0)


# ---------------------------------------------------------------------------
# Cohere embedding
# Fields: response.meta.billed_units.input_tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohere_embedding_maps_batch_usage(monkeypatch):
    from brainpalace_server.providers.embedding import cohere as ce

    class _BilledUnits:
        input_tokens = 42

    class _Meta:
        billed_units = _BilledUnits()

    class _Embeddings:
        float_ = [[0.1, 0.2], [0.3, 0.4]]

    class _Resp:
        embeddings = _Embeddings()
        meta = _Meta()

    class _Client:
        async def embed(self, **k):
            return _Resp()

    prov = ce.CohereEmbeddingProvider.__new__(ce.CohereEmbeddingProvider)
    prov._model = "embed-english-v3.0"
    prov._batch_size = 96
    prov._input_type = "search_document"
    prov._truncate = "END"
    prov._client = _Client()
    embs, usage = await prov._embed_batch_with_usage(["a", "b"])
    assert embs == [[0.1, 0.2], [0.3, 0.4]]
    assert usage == Usage(tokens_in=42, tokens_out=0, cache_read=0, cache_write=0)


# ---------------------------------------------------------------------------
# Ollama embedding
# DIVERGENCE from plan: uses AsyncOpenAI (OpenAI-compat) — response has
# usage.prompt_tokens, NOT prompt_eval_count.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_embedding_maps_batch_usage(monkeypatch):
    from brainpalace_server.providers.embedding import ollama as oll

    class _U:
        prompt_tokens = 38

    class _Item:
        def __init__(self, emb):
            self.embedding = emb

    class _Resp:
        data = [_Item([0.5, 0.6])]
        usage = _U()

    class _Embeddings:
        async def create(self, **k):
            return _Resp()

    prov = oll.OllamaEmbeddingProvider.__new__(oll.OllamaEmbeddingProvider)
    prov._model = "nomic-embed-text"
    prov._batch_size = 10
    prov._base_url = "http://localhost:11434/v1"
    prov._request_delay_ms = 0
    prov._max_retries = 3
    prov._client = type("Cl", (), {"embeddings": _Embeddings()})()
    embs, usage = await prov._embed_batch_with_usage(["a"])
    assert embs == [[0.5, 0.6]]
    assert usage == Usage(tokens_in=38, tokens_out=0, cache_read=0, cache_write=0)


# ---------------------------------------------------------------------------
# embed_texts_with_usage accumulates across batches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_texts_with_usage_accumulates_across_batches():
    """BaseEmbeddingProvider.embed_texts_with_usage sums Usage across batches."""
    from brainpalace_server.providers.base import BaseEmbeddingProvider, Usage

    class _FakeEmb(BaseEmbeddingProvider):
        provider_name = "Fake"  # type: ignore[assignment]

        def get_dimensions(self) -> int:
            return 2

        async def embed_text(self, text: str) -> list[float]:
            return [0.0, 0.0]

        async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.0, 0.0]] * len(texts)

        async def _embed_batch_with_usage(
            self, texts: list[str]
        ) -> tuple[list[list[float]], "Usage"]:
            return [[0.0, 0.0]] * len(texts), Usage(tokens_in=len(texts) * 10)

    prov = _FakeEmb(model="m", batch_size=2)
    # 5 texts at batch_size=2 → 3 batches (2+2+1)
    embs, usage = await prov.embed_texts_with_usage(["a", "b", "c", "d", "e"])
    assert len(embs) == 5
    # batch sizes: 2,2,1 → tokens_in: 20+20+10 = 50
    assert usage.tokens_in == 50

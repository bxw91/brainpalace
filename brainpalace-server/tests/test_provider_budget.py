"""Task 4b — billable-only per-hour spend cap + per-session chunk cap."""

from __future__ import annotations

from typing import Any

import pytest

from brainpalace_server.services.provider_budget import ProviderBudget, is_billable


def test_provider_budget_caps_per_hour() -> None:
    b = ProviderBudget(max_per_hour=2)
    assert b.allow(1000.0)
    b.record(1000.0)
    assert b.allow(1001.0)
    b.record(1001.0)
    assert b.allow(1002.0) is False  # at cap
    assert b.allow(1000.0 + 3601) is True  # window rolled


def test_provider_budget_zero_is_unlimited() -> None:
    b = ProviderBudget(max_per_hour=0)
    for t in range(1000):
        b.record(float(t))
    assert b.allow(0.0) is True


class _Summ:
    def __init__(self, provider: str, api_key: str | None) -> None:
        self.provider = provider
        self._api_key = api_key

    def get_api_key(self) -> str | None:
        return self._api_key


def test_is_billable() -> None:
    # ollama / local → never billable, even with a stray key value.
    assert is_billable(_Summ("ollama", None)) is False
    assert is_billable(_Summ("ollama", "x")) is False
    # keyless cloud provider → not billable (no $).
    assert is_billable(_Summ("openai", None)) is False
    # openai with a key → billable.
    assert is_billable(_Summ("openai", "sk-123")) is True
    # None settings → not billable (no provider to bill).
    assert is_billable(None) is False


@pytest.mark.asyncio
async def test_run_extraction_caps_chunks() -> None:
    """An oversized transcript yields <= provider_session_max_chunks LLM calls."""
    from brainpalace_server.services import session_distill_service as sd

    calls: list[str] = []

    class _Summarizer:
        async def generate(self, prompt: str) -> str:
            calls.append(prompt)
            # Return valid empty-ish JSON so parsing succeeds.
            return (
                '{"summary": "s", "open_threads": [], "decisions": [],'
                ' "files_touched": [], "tools_used": [], "triplets": [],'
                ' "records": []}'
            )

    meta = sd.SessionMeta(
        session_id="sid",
        project_path="/p",
        branch="main",
        started_at=None,
        ended_at=None,
        source_path="/p/sid.jsonl",
    )
    # 20 lines, tiny chunk_chars → would split into many parts; cap at 3.
    text = "\n".join(f"line {i} content here" for i in range(40))
    payload: Any = await sd._run_extraction(
        _Summarizer(),
        text,
        meta,
        "sid",
        chunk_chars=20,
        max_chunks=3,
    )
    assert payload is not None
    # 3 part-summaries + 1 merge call = 4; without the cap it would be far more.
    assert len(calls) <= 3 + 1

import pytest

from brainpalace_server.indexing.doc_triplet_extractor import extract_doc_triplets


class _FakeProvider:
    def __init__(self, reply: str, *, boom: bool = False) -> None:
        self._reply = reply
        self._boom = boom
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._boom:
            raise RuntimeError("provider down")
        return self._reply


@pytest.mark.asyncio
async def test_extracts_triplets_via_provider():
    prov = _FakeProvider(
        "FastAPI | uses | Pydantic\nBrainPalace | depends_on | ChromaDB"
    )
    triplets = await extract_doc_triplets(
        "FastAPI uses Pydantic.", "chunk_1", provider=prov, max_triplets=5
    )
    assert [(t.subject, t.predicate, t.object) for t in triplets] == [
        ("FastAPI", "uses", "Pydantic"),
        ("BrainPalace", "depends_on", "ChromaDB"),
    ]
    assert triplets[0].source_chunk_id == "chunk_1"
    assert len(prov.prompts) == 1  # one generate() call


@pytest.mark.asyncio
async def test_empty_text_skips_provider():
    prov = _FakeProvider("x | y | z")
    assert await extract_doc_triplets("   ", "c1", provider=prov) == []
    assert prov.prompts == []  # no call for empty text


@pytest.mark.asyncio
async def test_successful_call_no_relations_returns_empty_list():
    prov = _FakeProvider("no triplets here")  # parser finds nothing
    assert await extract_doc_triplets("prose", "c1", provider=prov) == []


@pytest.mark.asyncio
async def test_provider_failure_returns_none():
    prov = _FakeProvider("", boom=True)
    assert await extract_doc_triplets("some text", "c1", provider=prov) is None

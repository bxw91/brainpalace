from collections.abc import Iterable
from typing import Any

import pytest
from pydantic import ValidationError

from brainpalace_server.ingestion.adapter import (
    EmittedEntity,
    EmittedRecord,
    EmittedReference,
    SourceAdapter,
    known_adapters,
    register_adapter,
    reset_adapters,
)
from brainpalace_server.models.domains import is_known_domain
from brainpalace_server.models.record import RecordCandidate


@pytest.fixture(autouse=True)
def _clean_registry():
    # NOTE: reset_adapters() clears the adapter list, but register_adapter also
    # calls register_domain — and models/domains.py has NO reset (open set by
    # design). "monocle" therefore lingers in the global _DOMAINS for the rest of
    # the session. Harmless here (no test asserts the exact domain set), but any
    # future test asserting known_domains() equality must not depend on isolation.
    # (Deliberately NOT "glasses" — tests/models/test_domains.py already uses that
    # literal and asserts it starts unregistered; picking the same string here
    # would poison that test across the full suite via the same global registry.)
    reset_adapters()
    yield
    reset_adapters()


class _FakeAdapter:
    domain = "monocle"
    source = "monocle-transcript"

    def emit(self, payload: Any) -> Iterable[Any]:
        yield EmittedRecord(
            candidate=RecordCandidate(
                subject="wear", metric="duration", value=30.0, unit="min"
            ),
            id="fixed-id-1",
            domain=self.domain,
            source=self.source,
            source_id="sess-1",
            confidence=0.9,
        )


def test_emitted_record_defaults_to_eager():
    item = EmittedRecord(
        candidate=RecordCandidate(subject="s", metric="m", value=1.0),
        id="x",
        domain="code",
        source="src",
        source_id="sid",
        confidence=0.5,
    )
    assert item.mode == "eager"


def test_emitted_reference_defaults_to_lazy():
    item = EmittedReference(
        pointer="gmail://msg/1",
        summary="hi",
        domain="code",
        source="src",
        source_id="sid",
    )
    assert item.mode == "lazy"


def test_register_adapter_registers_its_domain():
    assert not is_known_domain("monocle")
    register_adapter(_FakeAdapter())
    assert is_known_domain("monocle")
    assert any(a.domain == "monocle" for a in known_adapters())


def test_emitted_entity_new_fields_default_empty():
    item = EmittedEntity(
        name="Ivan", kind="person", domain="code", source="src", source_id="sid"
    )
    assert item.aliases == []
    assert item.external_ref is None


def test_emitted_entity_accepts_aliases_and_external_ref():
    item = EmittedEntity(
        name="Ivan",
        kind="person",
        domain="code",
        source="src",
        source_id="sid",
        aliases=["Ivo"],
        external_ref="voice-cluster-3",
    )
    assert item.aliases == ["Ivo"]
    assert item.external_ref == "voice-cluster-3"


def test_emitted_entity_still_forbids_unknown_field():
    with pytest.raises(ValidationError):
        EmittedEntity(
            name="Ivan",
            kind="person",
            domain="code",
            source="src",
            source_id="sid",
            bogus="nope",
        )


def test_protocol_is_structural_no_inheritance():
    # _FakeAdapter does not subclass SourceAdapter but satisfies it.
    a: SourceAdapter = _FakeAdapter()
    items = list(a.emit(None))
    assert items[0].source == "monocle-transcript"

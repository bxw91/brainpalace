"""Neutral helper module for record extraction at the common persist sink.

Kept separate from session_distill_service and session_extract_service to
avoid the import cycle: session_distill_service already imports
SessionExtractService at module level.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable


def _rid(*parts: object) -> str:
    return hashlib.sha1(
        "|".join("" if p is None else str(p) for p in parts).encode()
    ).hexdigest()[:16]


def _with_salience(rec: Any) -> Any:
    from brainpalace_server.indexing.salience import score_salience

    return rec.model_copy(update={"salience": score_salience(rec)})


_COUNT_FIELDS: tuple[tuple[str, Callable[[Any], int]], ...] = (
    ("files_touched", lambda e: len(e.files_touched)),
    ("tools_used", lambda e: len(e.tools_used)),
    ("decisions", lambda e: len(e.decisions)),
    ("open_threads", lambda e: len(e.open_threads)),
)


def derived_count_records(extraction: Any, *, ingested_at: str) -> list[Any]:
    from brainpalace_server.indexing.record_validation import HIGH_CONFIDENCE
    from brainpalace_server.models.record import Record

    out: list[Any] = []
    for metric, fn in _COUNT_FIELDS:
        out.append(
            _with_salience(
                Record(
                    # value excluded from id → stable across re-distill
                    id=_rid(extraction.session_id, "session", metric),
                    subject="session",
                    metric=metric,
                    value=float(fn(extraction)),
                    unit="count",
                    ts=extraction.ended_at,
                    domain="chat-life",
                    source="session",
                    source_id=extraction.session_id,
                    ingested_at=ingested_at,
                    confidence=HIGH_CONFIDENCE,
                )
            )
        )
    return out


def records_to_store(extraction: Any, *, ingested_at: str) -> list[Any]:
    from brainpalace_server.indexing.record_validation import score_confidence
    from brainpalace_server.models.record import Record, RecordCandidate

    out: list[Any] = []
    for it in extraction.records:
        cand = RecordCandidate(
            subject=it.subject, metric=it.metric, value=it.value, unit=it.unit, ts=it.ts
        )
        out.append(
            _with_salience(
                Record(
                    id=_rid(
                        extraction.session_id, it.subject, it.metric, it.value, it.ts
                    ),
                    subject=it.subject,
                    metric=it.metric,
                    value=it.value,
                    unit=it.unit,
                    ts=it.ts,
                    domain="chat-life",
                    source="session",
                    source_id=extraction.session_id,
                    ingested_at=ingested_at,
                    confidence=score_confidence(cand),
                )
            )
        )
    return out


def _emit_from_record(rec: Any) -> Any:
    from brainpalace_server.ingestion.adapter import EmittedRecord
    from brainpalace_server.models.record import RecordCandidate

    return EmittedRecord(
        candidate=RecordCandidate(
            subject=rec.subject,
            metric=rec.metric,
            value=rec.value,
            unit=rec.unit,
            ts=rec.ts,
        ),
        id=rec.id,
        domain=rec.domain,
        source=rec.source,
        source_id=rec.source_id,
        confidence=rec.confidence,
        properties=rec.properties,
    )


class SessionRecordAdapter:
    """Eager adapter — the first real consumer of the ingestion contract.
    Reuses the existing record builders so the sink produces byte-for-byte
    identical rows (see tests/services/test_session_record_adapter.py)."""

    domain = "chat-life"
    source = "session"

    def emit(self, extraction: Any) -> list[Any]:
        # ingested_at is re-stamped by the sink; use a placeholder here since
        # the builders require it but the value is overwritten downstream.
        built = derived_count_records(extraction, ingested_at="") + records_to_store(
            extraction, ingested_at=""
        )
        return [_emit_from_record(r) for r in built]


def persist_records(
    store: Any, extraction: Any, *, ingested_at: str, sensitivity: str = "normal"
) -> int:
    # Records are persisted whenever session extraction reaches this sink —
    # there is no separate record-extraction switch. Whether extraction runs
    # at all is gated upstream by extraction.mode. Now routed through the
    # ingestion sink (provenance/domain enforced there); zero behavior change.
    # ``sensitivity`` inherits the source session's mark (propagation).
    if store is None:
        return 0
    from brainpalace_server.ingestion.sink import ingest

    counts = ingest(
        SessionRecordAdapter(),
        extraction,
        record_store=store,
        ingested_at=ingested_at,
        sensitivity=sensitivity,
    )
    return counts["records"]

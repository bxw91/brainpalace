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


def persist_records(store: Any, extraction: Any, *, ingested_at: str) -> int:
    # Records are persisted whenever session extraction reaches this sink —
    # there is no separate record-extraction switch. Whether extraction runs
    # at all is gated upstream by extraction.mode.
    if store is None:
        return 0
    recs = derived_count_records(
        extraction, ingested_at=ingested_at
    ) + records_to_store(extraction, ingested_at=ingested_at)
    # atomic delete+insert (idempotent re-persist)
    result: int = store.replace_source(extraction.session_id, recs)
    return result

---
last_validated: 2026-07-21
---

# Ingestion Contract (Phase 6)

An engine-side seam for getting typed data into BrainPalace from any source —
session extraction today, a future adapter (email, glasses transcripts, a
product's own event stream) tomorrow — without the engine growing a bespoke
integration per source.

> **Status — Phase 6.** The contract (`SourceAdapter`, `EmittedItem` union) and
> the sink (`ingestion/sink.py`) are live. The only adapter registered today is
> `SessionRecordAdapter` — session record emission was refactored to go through
> this seam with zero behavior change (see `tests/services/test_session_record_adapter.py`
> for the golden byte-for-byte proof). No external adapter ships in this phase.

## Why this exists, and the name

`services/*ExtractionAdapter` (`DocExtractionAdapter`, `SessionExtractionAdapter`)
already exists in this codebase, but that name is taken by graph-triplet
extraction — a different concern (pulling entities/relationships out of text
for the knowledge graph). This seam's contract is deliberately named
**`SourceAdapter`** to avoid confusion: a `SourceAdapter` emits typed ingestion
items (records, references, …); it has nothing to do with triplet extraction.

## The contract

```python
class SourceAdapter(Protocol):
    domain: str
    source: str
    def emit(self, payload: Any) -> Iterable[EmittedItem]: ...
```

`SourceAdapter` is a `Protocol` (structural typing) — an adapter does not need
to subclass anything, it only needs matching attributes/methods. Register one
with `register_adapter(adapter)`, which also calls `register_domain(adapter.domain)`
so the domain is a known one before anything is emitted. `known_adapters()`
returns the current registry; `reset_adapters()` is a test hook (the registry
is in-memory — adapters re-register at process startup, see `api/main.py`).

## `EmittedItem` — the four tiers

| Type | Tier | Routed by `ingest` (sync) | Routed by `aingest` (async) | Destination |
|------|------|--------------------------|-----------------------------|--------------|
| `EmittedRecord` | eager | Yes | Yes | `RecordStore` (`records` table) |
| `EmittedReference` | lazy | Yes | Yes | `ReferenceCatalogStore` (`reference_catalog` table) |
| `EmittedDocument` | — | No — **async-only tier** | **Yes** | `DocumentIngestService` (chunks + embeddings) |
| `EmittedEntity` | — | No — **async-only tier** | **Yes** | `IdentityStore` (`person` + `alias` + optional external `link`) |

`EmittedRecord` and `EmittedReference` both default their `mode` field
(`"eager"` / `"lazy"` respectively) so a caller never has to set it explicitly.

`EmittedDocument` **is** routed — but only on the async seam. Document ingest is
embed-bound I/O, so there is no sync `document_ingestor`; `aingest(...,
document_ingestor=...)` hands the items to `DocumentIngestService`, which chunks,
embeds, and stores them under the item's `domain`/`source`/`source_id` provenance
(the same service behind `POST /ingest/text` and `brainpalace ingest`). Emitting a
document from the *sync* `ingest()` raises `NotImplementedError` pointing at
`aingest`.

`EmittedEntity` **is** routed — but, like `EmittedDocument`, only on the async
seam. `aingest(..., identity_store=...)` lands each entity as one `upsert_person`
(sensitivity inherited from the call), a global `upsert_alias` per `aliases`
entry, and — when the entity carries an `external_ref` (a voice cluster / phone
number / face id) — one `external` `link` to that person. This is the identity
seam (person / alias / link): the engine stores *who someone is*, and a chunk→
person `link` is written separately through `POST /entities/link` after the text
lands (a link needs a `chunk_id`, which does not exist until after ingest).
Emitting an entity from the *sync* `ingest()` still raises `NotImplementedError`
pointing at `aingest`; emitting one on `aingest` with no `identity_store` bound
is a hard `ProvenanceError`.

### Ownership split — why confidence/id are adapter-owned

`id` and `confidence` are set by the **adapter**, not recomputed by the sink.
This is deliberate: `services/session_records.py` already builds records two
different ways — `derived_count_records` uses a fixed `HIGH_CONFIDENCE`,
`records_to_store` uses `score_confidence(candidate)` — and a sink that
uniformly recomputed confidence would silently change the count-record rows.
The sink only assembles the final `Record`, computes `salience`
(`score_salience`), and stamps `ingested_at` — the **single clock** for every
item in one `ingest()` call, regardless of how many sources or tiers it spans.

`EmittedRecord.properties` carries `Record.properties` through the seam so an
external eager adapter isn't lossy (the session adapter emits none).

## The sink — the one choke point

```python
def ingest(adapter, payload, *, record_store, reference_store=None, ingested_at) -> dict[str, int]
```

`ingest()` drains `adapter.emit(payload)`, validates **every** item, and only
after the full drain succeeds does it write anything. Enforcement rules:

- Every item must carry non-empty `domain`, `source`, `source_id`.
- `domain` must already be a known/registered domain
  (`models.domains.is_known_domain`).
- Any violation raises `ProvenanceError` — **and nothing from that `ingest()`
  call is written**, including earlier valid items in the same drain (see
  "Atomicity" below).

Items route by tier: `EmittedRecord` → grouped by `source_id`, written via
`record_store.replace_source(source_id, records)`; `EmittedReference` →
grouped by `source_id`, written via `reference_store.replace_source(source_id, refs)`.
`ingest()` returns `{"records": n, "references": m}`.

### Atomicity

Items are validated and accumulated in memory during the drain; the store
writes happen only after the drain completes without error. A `ProvenanceError`
raised on item *k* means items `0..k-1` — even if individually valid — are
never written. This is proven by
`tests/ingestion/test_sink.py::test_reject_is_atomic_nothing_written`.

### Zero-emit does NOT clear

The sink calls `record_store.replace_source(source_id, …)` (and the reference
equivalent) **only** for `source_id`s that actually emitted at least one item
of that tier. A source that emits zero eager records in a given `ingest()`
call leaves any of its prior rows untouched — unlike a bulk "always replace"
call, there is no implicit clear-on-empty. Session extraction always emits at
least 4 count records (`derived_count_records`), so this never surfaces on the
session path today. A future adapter that needs "emitting nothing means clear
this source's prior rows" must call `delete_by_source(source_id)` explicitly —
the sink does not infer that intent from an empty drain.

## The lazy tier — `ReferenceCatalogStore` (Option A1, minimal)

A second SQLite-WAL store (records-adjacent, mirrors `RecordStore`'s
connect/PRAGMA/idempotent-migration pattern), for sources that should be
**pointed to and summarized now, fetched-and-extracted on demand later** — an
email backlog, a large transcript archive — rather than eagerly promoted to
typed records.

```python
class ReferenceEntry(BaseModel):
    id: str; domain: str; source: str; source_id: str
    pointer: str; summary: str; ingested_at: str | None; properties: dict[str, str]
```

`ReferenceCatalogStore` supports `upsert`, `replace_source` (atomic swap per
`source_id`), `delete_by_source`, `list(domain=...)`, `resolve(id) -> pointer`,
`count()`, and the embedding surface: `search_summaries`, `set_embeddings`,
`unembedded_entries`, `count_unembedded`. `ref_id(pointer, source)` is a
content-hash id helper so re-ingesting the same pointer from the same source is
idempotent.

The `summary_embedding` column is **wired**: `aingest(...,
reference_embedder=...)` embeds emitted reference summaries and attaches them via
`set_embeddings` after the upsert, and `search_summaries` gives semantic search
over the catalog (surfaced by `GET /references` and the `brainpalace references`
CLI group). Binding no `reference_embedder` still lands the references, just
unembedded — an A1-compatible degrade, backfillable later via `count_unembedded`
/ `set_embeddings`. What remains unbuilt is a real fetch-and-extract *lazy
adapter*; wire one when the first lazy source needs it.

## Non-changes (deliberate scope boundary)

- **No new `QueryMode`.** Ingestion is a write path; nothing here touches the
  query router or `ai_guidance.md`.
- **`Record` model unchanged.** Provenance/domain enforcement lives at the
  sink boundary, not in the schema.
- **No graph-node schema change.** `EmittedEntity` now routes on `aingest` to
  the `IdentityStore` (G5), which owns its own SQLite tables (person / alias /
  link) — not the graph. Persons are *projected* one-way into the graph as
  nodes when GraphRAG is enabled, but identity is never read back out of it.
- **No new CLI command or endpoint.** Nothing here is a setup/config/install
  surface, so setup-surface parity is not triggered; dashboard parity's
  `coverage_maps.py` is untouched (a reference-catalog count in
  `brainpalace status` is deferred to the tier's first real consumer).

---
last_validated: 2026-07-18
---

# Building on BrainPalace

How to build a memory product (a home assistant, a document archive, any
multi-source consumer) on the BrainPalace engine — the supported surface,
and nothing else.

> **Positioning:** BrainPalace is a typed-memory & retrieval engine for AI
> agents — code & docs today, more domains as presets mature.

## The supported seam surface

Consumer code imports the engine ONLY through these modules (enforced for the
in-repo product by `scripts/check_import_boundary.py`; the same list is the
compatibility contract for external consumers):

| Seam module | What it gives you |
|---|---|
| `brainpalace_server.ingestion.adapter` | `SourceAdapter` Protocol + `EmittedRecord`/`EmittedReference`/`EmittedDocument`/`EmittedEntity` models |
| `brainpalace_server.ingestion.sink` | `ingest()` (sync, records/references) and `aingest()` (async, + documents) — the single write choke point |
| `brainpalace_server.indexing.record_validation` | `register_validator` / confidence scoring (teaching seam) |
| `brainpalace_server.indexing.salience` | `register_salience_scorer` |
| `brainpalace_server.models.domains` | `register_domain` / `known_domains` (open registry) |
| `brainpalace_server.services.query_service` | `QueryService.execute_query` read seam |
| `brainpalace_server.models.record` | `Record` DTO |
| `brainpalace_server.models.graph` | graph DTOs |
| `brainpalace_server.models.query` | `QueryRequest`/`QueryResponse` DTOs |

Everything else — `storage.*`, service internals, the `.brainpalace/` data
dir and its `*.db` files — is engine-internal and may change without notice.

## The three tiers — which Emitted* to use

- **`EmittedRecord` (eager)** — typed facts you own: sensor readings, counts,
  measurements. Lands in the records store; `compute`/`scan`/`absence` query
  it.
- **`EmittedReference` (lazy)** — remote-owned items: an email, a Drive file.
  Stores pointer + summary only; fetch-and-extract on demand.
- **`EmittedDocument`** — derived text you produced: OCR of a scan, an STT
  transcript, an image description. Chunked + embedded + searchable
  (bm25/vector/hybrid) under your provenance.
- **`EmittedEntity`** — *who someone is*. Routed on `aingest` to the identity
  store as a `person` (+ global `aliases`, + an optional `external_ref` link).
  See "Identity" below for the full person / alias / link seam.

## The provenance contract

Every emitted item carries `domain` / `source` / `source_id` (enforced — the
sink raises on anything missing). `ingested_at` is stamped by the engine.
Re-ingesting a `source_id` REPLACES its previous content (records, references
and document chunks alike); unchanged document text is not re-embedded, but
its metadata is refreshed. `sensitivity` set at ingest is enforced at query
time engine-side: non-`normal` rows are hidden unless the interactive caller
opts in.

`sensitivity` is normally set once per batch (the request/call-level default),
but `EmittedDocument` and its HTTP mirror `IngestDoc` also accept an optional
per-item `sensitivity` override (`item.sensitivity or call_default`) — a mixed
batch (e.g. one capture burst with both public and private items) doesn't
need to split into N calls. `EmittedRecord`/`EmittedReference` are unaffected;
their sensitivity stays batch-level.

## Forgetting a source (cascade delete)

`DELETE /ingest/text/{source_id}` keeps its original, narrower meaning:
document chunks only (a published contract pinned by
`e2e/integration/test_share_receive_convention.py`). To forget a `source_id`
across **all three tiers** in one call, use `DELETE
/ingest/source/{source_id}`: it cascades document chunks (including identity
links, via `DocumentIngestService.delete_source`), typed records
(`RecordStore.delete_by_source`) and references
(`ReferenceCatalogStore.delete_by_source`), and returns per-tier counts
(`chunks_deleted`, `records_deleted`, `references_deleted`). Each tier is
best-effort independently — a keyless server (no document-ingest service) or
a caller missing a store still gets a forget over whichever tiers are
present. **Persons and aliases survive** — identity is user-asserted ground
truth, never derived from the deleted text. Both delete endpoints invalidate
the query cache so a deleted source stops appearing in a cached hit.

## Enumerating what you've ingested

Two read endpoints let a consumer audit or reconcile its own ingested
documents without a companion database: `GET
/ingest/sources?domain=&source=` lists distinct ingested `source_id`s with
`domain`, `source`, `chunk_count` and `ingested_at`; `GET
/ingest/text/{source_id}?offset=&limit=` pages that source's chunks (id,
text, metadata), ordered by chunk index. Both apply the same
sensitivity default-deny as query: a chunk marked non-`normal` is hidden
unless `include_sensitive=true`, so a source whose only chunks are sensitive
disappears from the default listing entirely. An empty or unknown
`source_id`/index returns an empty list (`total: 0`), never a 404. This
enumeration scope is documents only — records and references already have
their own list surfaces (`GET /references`, records `distinct_sources` via
stats).

## Identity (person / alias / link)

The engine has a first-class home for *who someone is*, so a multi-source
consumer (e.g. a home assistant) can attribute text to people, resolve
ambiguous references, and correct mistakes — without the engine ever touching a
microphone, a camera, or a recognition model.

**The seam split — engine stores + ranks, the app picks.** The engine stores
`person` rows (a null name IS the "unknown person"), scoped + time-bounded
`alias` bindings, and `link` rows (`speaker` / `mentioned` / `participant`, or
an opaque `external` key like a voice cluster / phone number). Given a surface
string + scope + time, it returns a **ranked candidate list with evidence** and
**never picks a winner** — the confidence threshold, the decision, and the
asking-the-user all live in the consumer app. Every link carries a `method`
(`user_asserted` vs `llm_inferred` vs `call_log` …) and is retractable, so an
inferred attribution is structurally distinguishable from an asserted one.

**How you reach it.** Emit an `EmittedEntity` on `aingest` to assert a person +
aliases; then use the identity API for links and resolution:

| Endpoint / CLI | Purpose |
|---|---|
| `POST /entities/person` · `brainpalace entities person` | Upsert a person (naming an unknown one is an update in place) |
| `POST /entities/alias` · `entities alias` | Bind a surface to a person (scoped + time-bounded) |
| `POST /entities/link` · `entities link` | Attach a chunk/session/span/external ref, or record it unresolved |
| `DELETE /entities/link/{link_id}` | Retract a link (never touches the chunk or its text) |
| `GET /entities/resolve` · `entities resolve` | Ranked candidates + evidence — never picks |
| `GET /entities/unresolved` · `entities unresolved` | The unresolved-link bucket |
| `POST /entities/backfill` · `entities backfill` | Re-score unresolved links against current aliases (one new alias retires many ambiguities) |

A chunk→person link needs a `chunk_id`, which does not exist until after
ingest — so links are written *after* the text lands, not carried on the
`EmittedEntity`. A `link.ref` for a `speaker` is the stable address
`"{source_id}#{idx}"` (resolved to the live chunk at read time), so correcting a
transcript never orphans an attribution; a re-ingest that changes a position's
text marks the affected `mentioned` links `stale` rather than deleting them.
Identity is user-asserted ground truth in its own SQLite store — never a
rebuildable cache, and never read back out of the knowledge graph (persons are
projected one-way into the graph as nodes when GraphRAG is on, for traversal
only). Non-`normal`-sensitivity persons are hidden from default person-filtered
queries, matching the chunk-level default-deny.

## Folder authority (Phase 6.5)

Indexed folders (and the chunks they produce) carry a binary `authority`:
`authoritative` or `reference` (missing/unset means `authoritative`). A folder
registered from OUTSIDE the project tree (`folders add --allow-external`)
defaults to `reference` — it cannot claim `authoritative`, nor claim the
project's own `domain` (config `project.domain`, default `code`), without an
explicit `--force`. At query time, `ranking.reference_rank_penalty` (default
`0.7`) soft-multiplies the rank of `reference`-authority results so an
external consumer's own data doesn't outrank the project's authoritative
content by default; `0.0` excludes reference results from output entirely
(still indexed). Set `--domain`/`--authority` explicitly on `folders add` to
control this per folder.

## Making references discoverable

References are directly searchable (Round 2 Plan C — no longer needs a
companion `EmittedDocument` since v2026.07). The lazy-source lifecycle:

1. **Emit** an `EmittedReference` (pointer + summary). If `aingest`'s
   `reference_embedder` is bound (sync `ingest` never embeds), the summary
   is embedded at write time; otherwise `brainpalace references
   embed-missing` (or `POST /references/embed-missing`) backfills it later.
2. **Search finds it** by meaning: `brainpalace references search "<query>"`
   / `POST /references/search` cosine-ranks embedded summaries. Top hits
   also surface inline in `hybrid`/`vector`/`multi`/`graph` query results,
   tagged `type: reference`, so a caller never has to search references
   separately to notice one exists.
3. **Resolve** the match to its pointer: `brainpalace references resolve
   <id>` (client-side lookup by id over `GET /references`) prints the
   stored pointer + summary.
4. **Ingest the body** once you need the full content searchable:
   `POST /ingest/text` (or `brainpalace ingest`) with the **same
   `source_id`** as the reference — the body lands as a normal document
   under that provenance, chunked/embedded/searchable like any other
   ingested text.

No longer needed since v2026.07: emitting a companion `EmittedDocument`
alongside every reference just to make it findable — references now carry
their own summary-embedding search path.

## Connection modes

- **In-process** (recommended for a single-process consumer): depend on
  `brainpalace-rag`, import the seams above, call `aingest`/`QueryService`.
- **HTTP**: `POST /ingest/text`, `POST /ingest/records`, `POST
  /ingest/references`, `DELETE /ingest/text/{source_id}`, `DELETE
  /ingest/source/{source_id}`, `GET /ingest/sources`, `GET
  /ingest/text/{source_id}`, the query API, `brainpalace ingest` CLI. All
  three emit tiers (records, references, documents) now have an HTTP write
  path — records and references route through the same `aingest` choke point
  as the in-process seam, via a one-shot adapter built in the router
  (`brainpalace_server.ingestion.sink.items_adapter`), so provenance
  validation, salience scoring and `ingested_at` stamping are identical
  either way. `POST /ingest/records` and `POST /ingest/references` work
  keyless: records land normally, references land unembedded and are
  backfillable via `POST /references/embed-missing`.
- Scoped setup for a data consumer:
  `brainpalace init -F data/derived --language hr` — index only your derived
  folder, never your source tree. Folders **outside** the project tree work
  too: the server rejects out-of-tree paths unless the request opts in with
  `allow_external` — `init -F /outside/tree` opts in automatically for
  external targets; after init, use
  `brainpalace folders add /outside/tree --allow-external`. A
  records/references-only start needs no embedding key
  (`init --start --no-watch`); the first embedding operation
  will name the missing env var.

## Receiving a share (household multi-instance)

The household model is N personal BrainPalace instances plus (optionally) one
shared instance; a "household read" is your instance merged with a sibling's.
The client-side merge ships as `brainpalace query "<q>" --also <path-or-url>`
(repeatable): it queries the current instance and each `--also` instance, then
RRF-merges (rank fusion — raw scores are not comparable across instances) and
tags each result with its instance. `--json` results carry an `"instance"` key
(`"local"` for the current instance, the path/URL string for siblings); a down
sibling prints a warning and is skipped, local results still render.

Sharing is **copy-on-consent**: the recipient's instance owns its own copy of
a shared item — there is no live cross-instance link. A received share is an
`/ingest/text` write with a fixed provenance shape:

| Field | Value |
|---|---|
| `domain` | `"shared"` |
| `source` | `"shared-from:<person>"` |
| `source_id` | sender-scoped id (stable per shared item) |
| `metadata.shared_by` | `"<person>"` |
| `metadata.shared_at` | ISO-8601 timestamp |
| `sensitivity` | as the sender marked it |

The item then appears in normal `bm25`/`vector`/`hybrid` queries under source
`ingest://shared/shared-from:<person>/<source_id>`. **Retract-on-TTL** is a
consumer-side policy: the recipient schedules
`DELETE /ingest/text/{source_id}` (the engine half shipped in Round 1) when the
share expires. Re-sending the same `source_id` replaces the copy in place.

This convention is pinned by an integration test
(`e2e/integration/test_share_receive_convention.py`): ingest a share → find it
→ delete it → gone.

### When to build server-side federation (M2 demand test)

Read-merge above is deliberately **client-side only** — no server federation
code exists, and the roster/pairing/consent/transport layer is agent-app work,
not engine work. Server-side federation (the server fanning out to siblings and
RRF-merging, which additionally requires instance auth — instances bind
localhost-only today) gets built only when a consumer demonstrates **at least
one** of the following:

> (a) merge latency across 3+ instances is unacceptable client-side, (b) a
> consumer that cannot run the CLI/client needs merged reads, (c)
> cross-instance pagination/dedup logic is being reimplemented by a second
> consumer.

Until one of these is demonstrated, the supported surface is `query --also`
plus the share-receive convention above.

## Testing your consumer

`RecordStore` and `ReferenceCatalogStore` take a `db_path` — point them at a
tmp dir. The sink is a plain function over those stores: see
`brainpalace-server/tests/ingestion/test_sink.py` for the fixture pattern.

## Stability & versioning

BrainPalace releases are CalVer. The seam modules above are the compatibility
surface: breaking changes to them are announced in `docs/CHANGELOG.md` with a
deprecation note one release ahead. Engine internals carry no such promise.

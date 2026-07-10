---
name: brainpalace-ingest
description: Ingest content into BrainPalace with caller-supplied provenance
skills:
  - using-brainpalace
last_validated: 2026-07-10
parameters:
---

# Ingest

## Purpose

Ingests content into BrainPalace with caller-supplied provenance
(`--domain`, `--source`, `--source-id`). `ingest` is a command group:

- **Bare `ingest FILE`** — ingest free text (from a file or stdin) as searchable
  content. The text is chunked, embedded and indexed, and shows up in
  `bm25`/`vector`/`hybrid` queries with source
  `ingest://<domain>/<source>/<source-id>`. Re-ingesting the same `--source-id`
  replaces its chunks (unchanged text is not re-embedded, but its metadata is
  refreshed). `--delete --source-id ID` removes all chunks for that id.
- **`ingest record`** — write one caller-asserted typed record (eager tier:
  `subject`/`metric`/`value`). Re-ingesting the same `--source-id` replaces its
  records. Works without an embedding provider.
- **`ingest reference`** — write one lazy-tier reference (`--pointer` +
  `--summary`). Summaries embed at write time when a provider is configured,
  otherwise they land unembedded and `brainpalace references embed-missing`
  backfills them.

### Examples

```
echo "invoice, July 2026" | /brainpalace:brainpalace-ingest - --domain home --source scanner --source-id inv-42
/brainpalace:brainpalace-ingest notes.txt --domain home --source notes --source-id n1 --metadata page=1 --language en
/brainpalace:brainpalace-ingest --delete --source-id inv-42
/brainpalace:brainpalace-ingest record --subject electricity --metric kwh --value 420 --domain home --source meter --source-id bill-1
/brainpalace:brainpalace-ingest reference --pointer file:///scan/bill-1.pdf --summary "electricity bill" --domain home --source scanner --source-id bill-1
```

## Usage

```
/brainpalace:brainpalace-ingest <file|-> --domain D --source S --source-id ID [options]
/brainpalace:brainpalace-ingest --delete --source-id ID
/brainpalace:brainpalace-ingest record --subject S --metric M --value V --domain D --source SRC --source-id ID [options]
/brainpalace:brainpalace-ingest reference --pointer P --summary TXT --domain D --source SRC --source-id ID [options]
```

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Missing provenance | `--domain`/`--source`/`--source-id` not all given | Provide all three (or use `--delete --source-id` for deletion) |
| Server not running | BrainPalace server is stopped | Run `brainpalace start` first |
| Reserved metadata key | `--metadata` uses a reserved key (e.g. `domain`) | Choose a different key name |

## Notes

- Use `-` as the file argument to read text from stdin.
- `--sensitivity` marks ingested rows (non-`normal` rows are hidden by default at query time).
- `--language` sets the BM25 tokenizer language override for the ingested text.
- `record` / `reference` writes work without an embedding provider; references
  land unembedded and are backfilled by `references embed-missing`.

### Flags
<!--GENERATED:flags-->
_This command takes no top-level flags._
<!--/GENERATED-->

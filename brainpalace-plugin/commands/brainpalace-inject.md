---
name: brainpalace-inject
description: Inject custom metadata into chunks during indexing via Python scripts or JSON metadata files
parameters:
  - name: script
    type: path
    required: false
    default: ""
  - name: folder-metadata
    type: path
    required: false
    default: ""
  - name: dry-run
    type: bool
    required: false
    default: false
  - name: url
    type: text
    required: false
    default: ""
  - name: chunk-size
    type: integer
    required: false
    default: 512
  - name: chunk-overlap
    type: integer
    required: false
    default: 50
  - name: no-recursive
    type: bool
    required: false
    default: false
  - name: include-code
    type: bool
    required: false
    default: true
  - name: languages
    type: text
    required: false
    default: ""
  - name: code-strategy
    type: choice
    required: false
    default: ast_aware
  - name: include-patterns
    type: text
    required: false
    default: ""
  - name: include-type
    type: text
    required: false
    default: ""
  - name: exclude-patterns
    type: text
    required: false
    default: ""
  - name: force
    type: bool
    required: false
    default: false
  - name: allow-external
    type: bool
    required: false
    default: false
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-07-21
---

# Content Injection

## Purpose

Enrich chunk metadata during indexing using custom Python scripts or static JSON metadata. Injectors run after chunking but before embedding (Step 2.5 in the pipeline), so enriched metadata is stored alongside vectors in the index.

At least one of `--script` or `--folder-metadata` must be provided.

## Usage

```
/brainpalace:brainpalace-inject <path> --script <script.py>
/brainpalace:brainpalace-inject <path> --folder-metadata <metadata.json>
/brainpalace:brainpalace-inject <path> --script <script.py> --folder-metadata <metadata.json>
/brainpalace:brainpalace-inject <path> --script <script.py> --dry-run
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| path | Yes | - | Path to documents to index |
| --script | No* | - | Python script exporting `process_chunk(chunk: dict) -> dict` |
| --folder-metadata | No* | - | JSON file with static key-value metadata |
| --dry-run | No | false | Validate injector against sample chunks without creating a job |
| --chunk-size | No | 512 | Target chunk size in tokens |
| --chunk-overlap | No | 50 | Overlap between chunks in tokens |
| --no-recursive | No | false | Don't scan subdirectories |
| --include-code / --no-code | No | true (ON) | Include code files in indexing (use --no-code for doc-only) |
| --include-type | No | - | File type presets (e.g., python,docs) |
| --languages | No | - | Comma-separated language list for code |
| --code-strategy | No | ast_aware | Code splitting: ast_aware or text_based |
| --include-patterns | No | - | Additional glob include patterns |
| --exclude-patterns | No | - | Additional glob exclude patterns |
| --force | No | false | Force re-indexing (bypass manifest) |
| --allow-external | No | false | Allow paths outside project directory |
| --json | No | false | Output results as JSON |

*At least one of `--script` or `--folder-metadata` is required.

### Examples

```
# Add project tags via script
/brainpalace:brainpalace-inject ./docs --script enrich.py

# Merge static metadata from JSON
/brainpalace:brainpalace-inject ./src --folder-metadata project-meta.json --include-code

# Combine script + static metadata
/brainpalace:brainpalace-inject ./docs --script classify.py --folder-metadata team-meta.json

# Validate before indexing
/brainpalace:brainpalace-inject ./docs --script enrich.py --dry-run

# With file type presets
/brainpalace:brainpalace-inject ./src --script enrich.py --include-type python,docs
```

## Execution

Run the inject command with appropriate options:

**Script injection:**
```bash
brainpalace inject <path> --script <script.py>
```

**Folder metadata injection:**
```bash
brainpalace inject <path> --folder-metadata <metadata.json>
```

**Dry-run validation:**
```bash
brainpalace inject <path> --script <script.py> --dry-run
```

### Expected Output

**Normal injection:**
```
Inject job queued!

Job ID: abc123
Folder: /home/dev/docs
Script: /home/dev/enrich.py
Status: queued

Use 'brainpalace jobs' to monitor progress.
```

**Dry-run:**
```
Dry-run validation complete

Sampled: 3 files, 10 chunks
Script: /home/dev/enrich.py
Keys added: ["project", "team", "category"]
Errors: 0

Ready to run without --dry-run.
```

## Injector Script Protocol

Scripts must export a `process_chunk` function:

```python
def process_chunk(chunk: dict) -> dict:
    """Enrich a single chunk with custom metadata."""
    chunk["project"] = "my-project"
    chunk["team"] = "backend"
    return chunk
```

**Input keys available** (from chunk metadata; not the chunk text): `chunk_id`, `source`, `language`, `start_line`, `end_line`, and `docstring` (optional). Additional metadata keys (`file_name`, `chunk_index`, `total_chunks`, `source_type`, etc.) are also present.

**Constraints:**
- Values must be scalars (str, int, float, bool) — lists and dicts are stripped for ChromaDB compatibility
- Keys in the core schema (`chunk_id`, `source`, etc.) cannot be overwritten
- Exceptions are caught per-chunk and logged as warnings (pipeline continues)
- Scripts should be pure functions with no side effects

See `docs/INJECTOR_PROTOCOL.md` for the full protocol specification with examples.

## Folder Metadata JSON Format

```json
{
  "project": "my-project",
  "team": "backend",
  "version": "2.0"
}
```

All key-value pairs are merged into every chunk from the folder. Same scalar value constraint applies.

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| No injection option | Neither --script nor --folder-metadata provided | Provide at least one |
| Script not found | Invalid path to .py file | Verify script path exists |
| Metadata file not found | Invalid path to .json file | Verify JSON file path exists |
| Script missing process_chunk | Script doesn't export required function | Add `def process_chunk(chunk: dict) -> dict` |
| Server not running | BrainPalace server is stopped | Run `brainpalace start` first |
| Non-scalar value stripped | List or dict in metadata | Use only str, int, float, bool values |

### Recovery Commands

```bash
# Validate script first
brainpalace inject ./docs --script enrich.py --dry-run

# Check server status
brainpalace status

# Monitor job progress
brainpalace jobs --watch
```

## Notes

- Inject is a superset of index — all index options are available
- Injection happens at Step 2.5 in the pipeline (after chunking, before embedding)
- Per-chunk errors don't crash the pipeline — they're logged as warnings
- Paths are resolved to absolute before sending to the server
- Use `--dry-run` to validate scripts before committing to a full indexing run

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --script | path | "" | Python script exporting process_chunk(chunk: dict) -> dict |
| --folder-metadata | path | "" | JSON file with static metadata to merge into all chunks |
| --dry-run | bool | false | Validate injector script against sample chunks without indexing |
| --url | text | "" | BrainPalace server URL (default: from config or http://127.0.0.1:8000) |
| --chunk-size | integer | 512 | Target chunk size in tokens (default: 512) |
| --chunk-overlap | integer | 50 | Overlap between chunks in tokens (default: 50) |
| --no-recursive | bool | false | Don't scan folder recursively |
| --include-code | bool | true | Index source code files alongside documents (default: ON). Use --no-code for doc-only repos. |
| --languages | text | "" | Comma-separated list of programming languages to index |
| --code-strategy | choice | ast_aware | Strategy for chunking code files (default: ast_aware) |
| --include-patterns | text | "" | Comma-separated additional include patterns (wildcards supported) |
| --include-type | text | "" | Comma-separated file type presets to include (e.g., python,docs,typescript). Use 'brainpalace types list' to see all available presets. |
| --exclude-patterns | text | "" | Comma-separated additional exclude patterns (wildcards supported) |
| --force | bool | false | Force re-indexing even if embedding provider has changed |
| --allow-external | bool | false | Allow indexing paths outside the project directory |
| --json | bool | false | Output as JSON |
<!--/GENERATED-->

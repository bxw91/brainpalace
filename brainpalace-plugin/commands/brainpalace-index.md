---
name: brainpalace-index
description: Index documents for semantic search
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: chunk-size
    type: integer
    required: false
    default: ""
  - name: chunk-overlap
    type: integer
    required: false
    default: ""
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
  - name: force-budget
    type: bool
    required: false
    default: false
  - name: allow-external
    type: bool
    required: false
    default: false
  - name: watch
    type: choice
    required: false
    default: ""
  - name: watch-debounce
    type: integer
    required: false
    default: ""
  - name: estimate
    type: bool
    required: false
    default: false
  - name: rebuild-graph
    type: bool
    required: false
    default: false
  - name: json
    type: bool
    required: false
    default: false
  - name: "yes"
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-07-10
---

# Index Documents

## Purpose

Indexes documents at the specified path for semantic search. Processes markdown, PDF, text, and optionally code files. Creates vector embeddings for semantic search and builds the BM25 index for keyword search. Supports incremental indexing — only changed files are re-processed on subsequent runs.

## Usage

```
/brainpalace:brainpalace-index <path> [options]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| path | Yes | - | Path to documents (file or directory) |
| --include-code / --no-code | No | true (ON) | Include code files (.py, .ts, .js, .java, etc.); --no-code for doc-only |
| --watch | No | unchanged | Enable (`auto`) or disable (`off`) live re-indexing of this folder |
| --watch-debounce | No | 30 | Debounce window (seconds) before a watched change re-indexes |
| --include-type | No | - | File type presets (e.g., python,docs,typescript). Use `brainpalace types list` to see all. |
| --chunk-size | No | 512 | Target chunk size in tokens |
| --chunk-overlap | No | 50 | Overlap between chunks in tokens |
| --no-recursive | No | false | Don't scan subdirectories |
| --languages | No | - | Comma-separated language list for code files |
| --code-strategy | No | ast_aware | Code splitting strategy: ast_aware or text_based |
| --include-patterns | No | - | Additional glob include patterns |
| --exclude-patterns | No | - | Additional glob exclude patterns |
| --estimate | No | false | Print an approximate embedding-token estimate and exit — does NOT index. Uses the same .gitignore/exclude/file-type rules as a real index. |
| --force | No | false | Force re-indexing (bypass manifest, evict all prior chunks) |
| --allow-external | No | false | Allow indexing paths outside the project directory |
| --json | No | false | Output results as JSON |

### Examples

```
/brainpalace:brainpalace-index docs/
/brainpalace:brainpalace-index ./src --include-code
/brainpalace:brainpalace-index ./project --include-type python,docs
/brainpalace:brainpalace-index ./src --include-type typescript --include-patterns "*.json"
/brainpalace:brainpalace-index ./docs --force
/brainpalace:brainpalace-index ./src --include-code --chunk-size 1024
/brainpalace:brainpalace-index ./src --allow-external
```

## Execution

Run the appropriate command based on parameters:

**Index documents only:**
```bash
brainpalace index <path>
```

**Include code files:**
```bash
brainpalace index <path> --include-code
```

**With file type presets:**
```bash
brainpalace index <path> --include-type python,docs
```

**Estimate embedding-token cost before indexing (no indexing):**
```bash
brainpalace index <path> --estimate
```

**Force full re-index (bypass incremental):**
```bash
brainpalace index <path> --force
```

**With file watching (auto-reindex on changes):**
```bash
brainpalace folders add <path> --watch auto --include-code
brainpalace folders add <path> --watch auto --debounce 10
```

**With all options:**
```bash
brainpalace index <path> --include-code --include-type python,docs --chunk-size 1024 --force
```

### Expected Output

```
Indexing job queued!

Job ID: abc123
Folder: /home/dev/project/docs
Include types: python, docs
Status: queued

Use 'brainpalace jobs' to monitor progress.
```

**After completion (check with `brainpalace jobs <job_id>`):**

First-time indexing:
```
Files added: 45
Chunks created: 312
```

Incremental re-indexing:
```
Eviction Summary:
  Files added:     3
  Files changed:   2
  Files deleted:   1
  Files unchanged: 39
  Chunks evicted:  15
  Chunks created:  25
```

## Output

Report progress and results:

1. **Job Queued** — Show job ID and status
2. **Monitor Progress** — Use `brainpalace jobs --watch`
3. **Completion Summary** — Eviction summary for incremental runs

### Supported File Types

| Category | Extensions |
|----------|------------|
| Documents | `.md`, `.txt`, `.pdf`, `.rst` |
| Code (with --include-code) | `.py`, `.ts`, `.js`, `.java`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.cs` |

### File Type Presets (with --include-type)

| Preset | Extensions |
|--------|------------|
| python | `.py`, `.pyi`, `.pyw` |
| javascript | `.js`, `.jsx`, `.mjs`, `.cjs` |
| typescript | `.ts`, `.tsx` |
| go | `.go` |
| rust | `.rs` |
| java | `.java` |
| csharp | `.cs` |
| c | `.c`, `.h` |
| cpp | `.cpp`, `.hpp`, `.cc`, `.hh` |
| web | `.html`, `.css`, `.scss`, `.jsx`, `.tsx` |
| docs | `.md`, `.txt`, `.rst`, `.pdf` |
| text | `.md`, `.txt`, `.rst` |
| pdf | `.pdf` |
| code | All language presets combined |

Use `brainpalace types list` to see all available presets.

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Path not found | Invalid path specified | Verify the path exists |
| No files found | Path contains no supported files | Check file extensions or use --include-type |
| Server not running | BrainPalace server is stopped | Run `brainpalace start` first |
| Embedding provider error | Provider not configured | Run `/brainpalace:brainpalace-config` |
| Permission denied | Cannot read files | Check file permissions |
| Queue full (429) | Too many concurrent jobs | Wait or cancel with `brainpalace jobs JOB_ID --cancel` |

### Recovery Commands

```bash
# Verify server is running
brainpalace status

# Diagnose setup and configuration
brainpalace doctor

# Monitor job progress
brainpalace jobs --watch

# Force full re-index if incremental fails
brainpalace index <path> --force
```

## Notes

- Indexing runs asynchronously via job queue — use `brainpalace jobs` to monitor
- Incremental indexing: only changed/new files are processed (unchanged files skipped)
- Use `--force` to bypass manifest tracking and fully re-index
- Deleted files' chunks are automatically evicted during incremental re-indexing
- Use `brainpalace reset --yes` to clear the entire index before re-indexing
- Large directories may take several minutes
- Code files require AST parsing and may be slower
- Binary files and images are automatically skipped
- Relative paths are resolved from the current directory
- Use `/brainpalace:brainpalace-inject` to enrich chunks with custom metadata during indexing
- Use `--watch auto` to enable automatic re-indexing when files change
- Watcher-triggered jobs use incremental diff for efficiency (only changed files processed)
- Directories like `.git/`, `node_modules/`, `__pycache__/`, `dist/`, `build/` are excluded from watching

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config or http://127.0.0.1:8000) |
| --chunk-size | integer | "" | Target chunk size in tokens (advanced; default 512). |
| --chunk-overlap | integer | "" | Token overlap between chunks (advanced; default 50). |
| --no-recursive | bool | false | Don't scan folder recursively |
| --include-code | bool | true | Index source code files alongside documents (default: ON). Use --no-code for doc-only repos. |
| --languages | text | "" | Comma-separated list of programming languages to index |
| --code-strategy | choice | ast_aware | Strategy for chunking code files (default: ast_aware) |
| --include-patterns | text | "" | Comma-separated additional include patterns (wildcards supported) |
| --include-type | text | "" | Comma-separated file type presets to include (e.g., python,docs,typescript). Use 'brainpalace types list' to see all available presets. |
| --exclude-patterns | text | "" | Comma-separated additional exclude patterns (wildcards supported) |
| --force | bool | false | Force re-indexing even if embedding provider has changed |
| --force-budget | bool | false | Bypass the per-job embedding-token budget cap for this job. |
| --allow-external | bool | false | Allow indexing paths outside the project directory |
| --watch | choice | "" | Enable ('auto') or disable ('off') live re-index on file changes for this folder. Default: leave the folder's current setting unchanged. |
| --watch-debounce | integer | "" | Debounce window in seconds before a watched folder re-indexes. |
| --estimate | bool | false | Estimate approximate embedding-token usage and exit — do not index. |
| --rebuild-graph | bool | false | Rebuild the graph index from already-indexed chunks (no embedding, no token cost); runs AST + LSP over the corpus and returns when complete. |
| --json | bool | false | Output as JSON |
| --yes | bool | false | Skip interactive confirmation prompts (e.g. extraction-backlog warning). |
<!--/GENERATED-->

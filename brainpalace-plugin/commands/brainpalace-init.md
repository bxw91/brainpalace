---
name: brainpalace-init
description: Initialize BrainPalace for the current project
parameters:
  - name: path
    type: directory
    required: false
    default: ""
  - name: host
    type: text
    required: false
    default: ""
  - name: port
    type: integer
    required: false
    default: ""
  - name: force
    type: bool
    required: false
    default: false
  - name: json
    type: bool
    required: false
    default: false
  - name: state-dir
    type: directory
    required: false
    default: ""
  - name: force-monorepo-root
    type: bool
    required: false
    default: false
  - name: start
    type: bool
    required: false
    default: ""
  - name: watch
    type: choice
    required: false
    default: ""
  - name: no-watch
    type: bool
    required: false
    default: false
  - name: "yes"
    type: bool
    required: false
    default: false
  - name: sessions
    type: bool
    required: false
    default: ""
  - name: archive
    type: bool
    required: false
    default: ""
  - name: compute
    type: bool
    required: false
    default: ""
  - name: extract
    type: bool
    required: false
    default: ""
  - name: git-history
    type: bool
    required: false
    default: ""
  - name: graphrag-extract
    type: bool
    required: false
    default: ""
  - name: migrate-graph-store
    type: bool
    required: false
    default: ""
  - name: language
    type: text
    required: false
    default: ""
  - name: reranking
    type: bool
    required: false
    default: ""
  - name: bm25-engine
    type: choice
    required: false
    default: ""
  - name: include-code
    type: bool
    required: false
    default: true
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-06-24
---

# Initialize BrainPalace Project

## Purpose

Initializes the current project for BrainPalace by creating the necessary configuration directory and files. This sets up per-project isolation, allowing each project to have its own BrainPalace instance with separate configuration and data.

## Usage

```
/brainpalace:brainpalace-init [--path <path>] [--host <host>] [--port <port>] [--force] [--state-dir <dir>] [--json]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --path / -p | No | Auto-detect | Project path (auto-detects git root or project markers) |
| --host | No | 127.0.0.1 | Server bind host |
| --port | No | Auto-select | Preferred server port (disables auto-port if set) |
| --force / -f | No | false | Overwrite existing configuration |
| --state-dir / -s | No | .brainpalace | Custom state directory for index data |
| --language | No | en | Project default BM25 language (ISO 639-1, e.g. `en`, `de`, `fr`). Written to `bm25.language` in the project config. |
| --bm25-engine | No | stem | BM25 tokenization engine: `stem` (Snowball/PyStemmer, ~27 languages) or `lemma` (simplemma, Croatian `hr` tier via the `hbs` data). |
| --include-code / --no-code | No | on | Index source code files alongside documents. Use `--no-code` for doc-only repos. Applies to BOTH the first index and the pre-index token estimate. |
| --git-history / --no-git-history | No | off | Index this repo's git commit history (message + changed-file list) as searchable chunks. **Off by default** — commit messages/diffs can contain secrets, so it is a deliberate opt-in. Interactive runs ask (default no); written to `git_indexing.enabled` only when enabled. |
| --migrate-graph-store / --no-migrate-graph-store | No | (ask) | On an **already-initialized** project still on the legacy `simple` graph store, upgrade `graphrag.store_type` to `sqlite` (persistent + temporal). Interactive runs ask (default **yes**); the existing graph is replayed into sqlite on next start (JSON kept for rollback). No effect on fresh inits or projects already on sqlite. |
| --start / --no-start | No | on when interactive | Start the server after init |
| --watch | No | auto (when starting) | Folder watch mode: `auto` (index + watch) or `off` |
| --no-watch | No | false | Do not register/watch the project folder |
| --yes / -y | No | false | Skip the confirmation prompt and apply defaults |
| --sessions / --no-sessions | No | off (default/--yes do NOT embed) | INDEX this project's AI chat transcripts (billable); pass `--sessions` to enable |
| --archive / --no-archive | No | on | ARCHIVE raw transcripts under `.brainpalace/` (free, independent of indexing) |
| --compute / --no-compute | No | on | COMPUTE query mode — set-level questions (sum/count/avg, by-week/month, "which … most") over typed numeric records from sessions. Free: counts piggyback session summaries, no extra API call. Interactive runs ask; written to `compute.enabled` + `compute.record_extraction` only on opt-out (`--no-compute`). |
| --force-monorepo-root | No | false | Allow init at a directory flagged as a monorepo root |
| --json | No | false | Output as JSON |

### Examples

```
/brainpalace:brainpalace-init
/brainpalace:brainpalace-init --path /my/project
/brainpalace:brainpalace-init --port 8080
/brainpalace:brainpalace-init --state-dir /custom/path
/brainpalace:brainpalace-init --force
/brainpalace:brainpalace-init --language de
/brainpalace:brainpalace-init --language hr --bm25-engine lemma
/brainpalace:brainpalace-init --git-history    # opt into git-history indexing
```

> **Git-history indexing (opt-in).** `init` can index your git commit history
> (commit message + changed-file list) into searchable chunks. It is **off by
> default** because commit messages and diffs can leak secrets. Interactive runs
> ask a yes/no question (default **no**); pass `--git-history` / `--no-git-history`
> to decide non-interactively. When enabled, `git_indexing.enabled: true` is
> written to `.brainpalace/config.yaml`. Nothing is copied — chunks reference the
> commit sha.

> **Graph store default.** New projects get GraphRAG enabled with the **`sqlite`**
> store (`graphrag.store_type: sqlite`): persistent, incrementally-writable, with
> temporal-validity tracking. (The legacy `simple` in-memory JSON store has no
> temporal tracking.)

> **Upgrading an existing project.** Projects created before `sqlite` became the
> default keep `store_type: simple`. Re-run `brainpalace init` to upgrade: an
> interactive run asks (default **yes**), or pass `--migrate-graph-store` /
> `--no-migrate-graph-store`. The server replays the existing `simple` JSON graph
> into sqlite on the next start (JSON kept for rollback); no re-indexing needed.

> **Pre-index token estimate (opt-in).** On an interactive run, before the first
> index `init` asks whether to estimate approximate embedding-token usage
> (default **no**, never shown under `--json`/CI). The estimate uses the same
> file-selection rules **and the same `--include-code`/`--no-code` scope** as the
> real index, and reflects your chosen embedding provider's tokenizer. After it
> prints you can **proceed**, **toggle code/docs scope and re-estimate**, or
> **skip** indexing. (Only the code/docs scope is re-asked here — provider /
> session / graph answers are already written and affect separate budgets.) Run
> it anytime with `brainpalace index <path> --estimate`.

## Execution

### Run Initialization

```bash
brainpalace init
brainpalace init --path /my/project
brainpalace init --port 8080
brainpalace init --state-dir /custom/path
brainpalace init --force

# Set the project BM25 language (default: en)
brainpalace init --language de

# Use the lemma engine for Croatian (requires brainpalace[lemma-hr])
brainpalace init --language hr --bm25-engine lemma
```

This creates the `.brainpalace/` directory structure in the project root.

> **Monorepo / nested layouts:** with `--path` absent, `init` **auto-detects the
> git root or project markers** — in a monorepo that can resolve a level *above*
> the subproject you meant. Pass `--path <subproject>` to target a specific
> subproject so each gets its own `.brainpalace/`. `init` flags a monorepo root
> and refuses to initialize there unless you pass `--force-monorepo-root`. At
> query time, server discovery then walks up to the nearest *initialized*
> `.brainpalace/`.

### Verify Initialization

```bash
ls -la .brainpalace/
```

## Output

```
BrainPalace Initialization
==========================

Initializing BrainPalace for current project...

Running: brainpalace init

Created directory structure:
  .brainpalace/
    config.yaml      - Project configuration (sparse — only values that diverge from global)
    chroma_db/       - Vector store (created on first index)
    bm25_index/      - Keyword index (created on first index)

Project initialized successfully!

Configuration file: .brainpalace/config.yaml

Next steps:
  1. Start server: /brainpalace:brainpalace-start
  2. Index documents: /brainpalace:brainpalace-index ./docs
  3. Search: /brainpalace:brainpalace-search "your query"
```

## What Gets Created

The initialization creates the following structure:

```
.brainpalace/
  config.yaml          # Project configuration (sparse — bind_host, port, chunk settings, exclude patterns, providers)
  data/
    chroma_db/         # ChromaDB vector store (created on index)
    bm25_index/        # BM25 keyword index (created on index)
    llamaindex/        # LlamaIndex persistence (created on index)
  logs/                # Server logs
```

### config.yaml

The project config is a **single YAML file** (`.brainpalace/config.yaml`) — there
is no `config.json`. It is **sparse**: `init` writes only values that diverge from
the inherited global (`~/.config/brainpalace/config.yaml`) and the code defaults,
which resolve `code < global < project`. `brainpalace config unset <dotpath>`
removes a project override so the key inherits again. It can hold server/index
settings (`bind_host`, `port_range_start`/`_end`, `auto_port`, `chunk_size`,
`chunk_overlap`, `exclude_patterns`, `project_root`) plus the provider / BM25 /
GraphRAG blocks below:

```yaml
# .brainpalace/config.yaml
project:
  state_dir: null  # Use default

embedding:
  provider: "openai"
  api_key: "sk-proj-..."  # Or use api_key_env: "OPENAI_API_KEY"

summarization:
  provider: "anthropic"
  api_key: "sk-ant-..."

# BM25 tokenization — written by `brainpalace init --language` / `--bm25-engine`
bm25:
  language: "en"           # ISO 639-1 project default (e.g. de, fr, es, ru, hr)
  engine: "stem"           # stem (Snowball/PyStemmer, ~27 languages) or lemma (simplemma)
  detect: false            # opt-in per-document language detection
  detect_min_confidence: 0.6  # minimum confidence to accept detected language (0–1)

# GraphRAG — written by `brainpalace init` (on by default)
graphrag:
  enabled: true
  store_type: "sqlite"     # default: persistent + temporal validity (simple = in-memory JSON, no temporal)
  use_code_metadata: true

# Git-history indexing — written ONLY when `--git-history` / the init prompt opts in
git_indexing:
  enabled: false           # opt-in; commit messages/diffs can contain secrets
```

**BM25 language notes:**
- `--language` / `bm25.language` sets the project default; `--bm25-engine` / `bm25.engine` controls the tokenizer.
- Supported languages: ~27 Snowball/PyStemmer codes (`en`, `de`, `fr`, `es`, `it`, `pt`, `nl`, `ru`, and more) plus a custom Croatian stemmer (`hr`). Unknown codes fall back to English.
- `engine: lemma` requires the `simplemma` library (Croatian lemmatization via the Serbo-Croatian `hbs` data). Install the optional extra: `pip install 'brainpalace[lemma-hr]'`. For all other languages, `engine: stem` is recommended.
- Changing `bm25.language` or `bm25.engine` changes tokenization; the BM25 index auto-rebuilds from the stored corpus on next server start (the analyzer fingerprint is persisted). To re-detect per-document languages, re-run indexing with `brainpalace index <path>`.

**Note**: BrainPalace merges config across `code < global < project`. The project file (`.brainpalace/config.yaml`) overrides the global XDG config (`~/.config/brainpalace/config.yaml`); the legacy `~/.brainpalace/` path is deprecated.

### runtime.json

Created when server starts, contains:

```json
{
  "schema_version": 1,
  "mode": "project",
  "project_root": "/path/to/project",
  "instance_id": "a1b2c3d4",
  "base_url": "http://127.0.0.1:49321",
  "bind_host": "127.0.0.1",
  "port": 49321,
  "pid": 12345,
  "started_at": "2025-01-31T12:00:00Z"
}
```

## Error Handling

### Already Initialized

```
Project already initialized.

Existing configuration found at: .brainpalace/config.json

Options:
  - Continue using existing configuration
  - Reset with: rm -rf .brainpalace && brainpalace init
  - Check status: brainpalace status
```

### Permission Denied

```
Error: Cannot create directory .brainpalace/

Permission denied.

Solutions:
1. Check directory permissions: ls -la .
2. Ensure write access to current directory
3. Create manually: mkdir -p .brainpalace
4. Check if .claude exists and is writable
```

### Not in a Project Directory

```
Warning: No git repository or project markers found.

BrainPalace will initialize here, but consider:
1. Navigate to your project root first
2. Initialize git: git init
3. Then run: brainpalace init
```

### Parent Directory Issues

```
Error: Cannot create .claude directory

The parent directory may not exist or is not writable.

Check:
1. Current directory exists: pwd
2. You have write permissions: ls -la .
3. Disk is not full: df -h .
```

## Re-initialization

To completely reset a project's BrainPalace configuration:

```bash
# Stop server if running
brainpalace stop

# Remove existing configuration
rm -rf .brainpalace

# Re-initialize
brainpalace init
```

**Warning**: This deletes all indexed documents. You will need to re-index after re-initialization.

## Multiple Projects

Each project should be initialized separately. BrainPalace uses the `.brainpalace/` directory to isolate:

- Configuration settings
- Vector store data
- BM25 index data
- Server runtime state

This allows running multiple BrainPalace instances for different projects simultaneously, each on its own port.

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --path | directory | "" | Project path (default: auto-detect project root) |
| --host | text | "" | Server bind host. Default: inherit from global config / code (127.0.0.1). Pass to override for this project. |
| --port | integer | "" | Preferred server port (default: auto-select from range) |
| --force | bool | false | Overwrite existing configuration |
| --json | bool | false | Output as JSON |
| --state-dir | directory | "" | Custom state directory for index data (default: .brainpalace) |
| --force-monorepo-root | bool | false | Allow init at a directory whose CLAUDE.md flags it as a mono-repo workspace root. Use only if you really want a project-level state dir at the workspace root. |
| --start | bool | "" | Start the server after init. Default: ON in an interactive terminal (after a confirmation) or with --yes; OFF in non-interactive/--json runs. --no-start forces config-only. |
| --watch | choice | "" | Folder watch mode when starting (auto = register + index project_root + live re-index). Default 'auto' when starting, else 'off'. |
| --no-watch | bool | false | Do not register/watch the project folder (alias for --watch off). |
| --yes | bool | false | Skip the confirmation prompt and apply the full resolved plan. |
| --sessions | bool | "" | INDEX this project's AI chat transcripts into searchable session memory (embeddings, billable). ON by default for new projects: interactive runs confirm (default yes), non-interactive runs enable it. Pass --no-sessions to opt out (archive still runs). |
| --archive | bool | "" | ARCHIVE raw transcripts under .brainpalace/ as a durable backup (no embeddings, independent of indexing). ON by default. Pass --no-archive to opt out. |
| --compute | bool | "" | COMPUTE query mode: answer set-level questions (sum/count/avg, by-week/month, 'which … most') over typed numeric records extracted from your sessions. ON by default (free — derived counts piggyback session summaries; no extra API call). Interactive runs ask. Pass --no-compute to disable the mode and its record extraction. |
| --extract | bool | "" | SUMMARIZE each session into durable knowledge (summary, decisions, triplets). ON by default, summarized ONLY inside Claude Code (the plugin, free on your Claude Code subscription — no separate API bill). The server does not summarize on its own. Pass --no-extract to opt out. |
| --git-history | bool | "" | INDEX this repo's git commit history (message + diff stat) as searchable chunks. OFF by default — commits can contain secrets, so this is a deliberate opt-in. Interactive runs ask (default no). |
| --graphrag-extract | bool | "" | Extract a knowledge graph from document text (installs the optional langextract dep on enable). |
| --migrate-graph-store | bool | "" | On an already-initialized project whose graph store is the legacy in-memory 'simple' backend, upgrade graphrag.store_type to 'sqlite' (persistent + temporal; the existing graph is replayed into sqlite on next start, with the JSON kept for rollback). Interactive runs ask (default yes). No effect on fresh inits or projects already on sqlite. |
| --language | text | "" | Project default natural language for BM25 indexing (ISO 639-1, e.g. en, de, hr). Passed → written to bm25.language; omitted → inherit from global config / code default (en). |
| --reranking | bool | "" | Two-stage reranking: a local cross-encoder re-scores the top candidates for finer relevance ordering. OFF by default — the local model needs the heavy reranker-local extra (~2.8 GB PyTorch). --reranking installs that extra and enables it; or set reranker.provider=ollama for a torch-free reranker. Writes reranker.enabled to config.yaml. |
| --bm25-engine | choice | "" | BM25 stemming engine: 'stem' (Snowball, no extra deps) or 'lemma' (simplemma, better recall for morphologically-rich languages). Passed → written to bm25.engine; omitted → inherit from global config / code default (stem). engine=lemma requires simplemma: pip install 'brainpalace[lemma-hr]'. |
| --include-code | bool | true | Index source code files alongside documents (default: ON). Use --no-code for doc-only repos. Applies to the first index and to the pre-index token estimate. |
<!--/GENERATED-->

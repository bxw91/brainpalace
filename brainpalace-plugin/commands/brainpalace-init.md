---
name: brainpalace-init
description: Initialize BrainPalace for the current project
parameters:
  - name: path
    description: "Project path (default: auto-detect project root)"
    required: false
  - name: host
    description: "Server bind host (default: 127.0.0.1)"
    required: false
  - name: port
    description: "Preferred server port (default: auto-select from range)"
    required: false
  - name: force
    description: Overwrite existing configuration
    required: false
    default: false
  - name: state-dir
    description: Custom state directory for index data
    required: false
  - name: json
    description: Output as JSON
    required: false
    default: false
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-06-06
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
| --git-history / --no-git-history | No | off | Index this repo's git commit history (message + changed-file list) as searchable chunks. **Off by default** — commit messages/diffs can contain secrets, so it is a deliberate opt-in. Interactive runs ask (default no); written to `git_indexing.enabled` only when enabled. |
| --migrate-graph-store / --no-migrate-graph-store | No | (ask) | On an **already-initialized** project still on the legacy `simple` graph store, upgrade `graphrag.store_type` to `sqlite` (persistent + temporal). Interactive runs ask (default **yes**); the existing graph is replayed into sqlite on next start (JSON kept for rollback). No effect on fresh inits or projects already on sqlite. |
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
    config.json      - Project configuration
    chroma_db/       - Vector store (created on first index)
    bm25_index/      - Keyword index (created on first index)

Project initialized successfully!

Configuration file: .brainpalace/config.json
{
  "project_name": "my-project",
  "created_at": "2025-01-31T12:00:00Z",
  "mode": "project"
}

Next steps:
  1. Start server: /brainpalace:brainpalace-start
  2. Index documents: /brainpalace:brainpalace-index ./docs
  3. Search: /brainpalace:brainpalace-search "your query"
```

## What Gets Created

The initialization creates the following structure:

```
.brainpalace/
  config.json          # Project configuration (bind_host, port, chunk settings, exclude patterns)
  data/
    chroma_db/         # ChromaDB vector store (created on index)
    bm25_index/        # BM25 keyword index (created on index)
    llamaindex/        # LlamaIndex persistence (created on index)
  logs/                # Server logs
```

### config.json

Contains project-specific settings:

```json
{
  "bind_host": "127.0.0.1",
  "port_range_start": 8000,
  "port_range_end": 8100,
  "auto_port": true,
  "chunk_size": 512,
  "chunk_overlap": 50,
  "exclude_patterns": [
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/target/**"
  ],
  "project_root": "/path/to/project"
}
```

### config.yaml (Optional)

Create a `config.yaml` in the project's `.brainpalace/` directory for project-specific provider settings:

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

**Note**: BrainPalace searches for config.yaml in multiple locations. Project-level config takes precedence over user-level (`~/.brainpalace/config.yaml`).

### runtime.json

Created when server starts, contains:

```json
{
  "port": 49321,
  "pid": 12345,
  "started_at": "2025-01-31T12:00:00Z",
  "state_dir": ".brainpalace"
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

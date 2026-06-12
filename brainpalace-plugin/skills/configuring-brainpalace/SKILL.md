---
name: configuring-brainpalace
description: |
  Installation and configuration skill for BrainPalace document search system.
  Use when asked to "install BrainPalace", "setup BrainPalace", "configure BrainPalace",
  "setting up document search", "installing brainpalace packages", "configuring API keys",
  "initializing project for search", "troubleshooting BrainPalace", "pip install brainpalace",
  "BrainPalace not working", "BrainPalace setup error", "configure embeddings provider",
  "setup ollama for BrainPalace", or "BrainPalace environment variables".
  Covers package installation, provider configuration, project initialization, and server management.
license: MIT
allowed-tools:
  - Bash
  - Read
metadata:
  version: 7.0.0
  category: ai-tools
  author: bxw91
  last_validated: 2026-06-12
---

# Configuring BrainPalace

Installation and configuration for BrainPalace document search with pluggable providers.

## Contents

- [Quick Setup](#quick-setup)
- [Setup Wizard](#setup-wizard)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Provider Configuration](#provider-configuration)
- [BM25 Language Configuration](#bm25-language-configuration)
- [Project Initialization](#project-initialization)
- [Verification](#verification)
- [When Not to Use](#when-not-to-use)
- [Reference Documentation](#reference-documentation)

---

## Multi-Runtime Support

BrainPalace supports multiple AI coding runtimes from a single canonical plugin source:

| Runtime | Install Command |
|---------|----------------|
| Claude Code | `brainpalace install-agent --agent claude` |
| OpenCode | `brainpalace install-agent --agent opencode` |
| Gemini CLI | `brainpalace install-agent --agent gemini` |

All runtimes share the same `.brainpalace/` data directory for indexes, configuration, and server state. The `install-agent` command converts the canonical plugin format into each runtime's native format automatically.

Use `--global` for user-level installation, or `--dry-run` to preview files before writing.

---

## Quick Setup

### Option A: Local with Ollama (FREE, No API Keys)

```bash
# 1. Install packages
pip install brainpalace-rag brainpalace-cli

# 2. Install and start Ollama
brew install ollama  # macOS
ollama serve &
ollama pull nomic-embed-text
ollama pull llama3.2

# 3. Configure for Ollama
export EMBEDDING_PROVIDER=ollama
export EMBEDDING_MODEL=nomic-embed-text
export SUMMARIZATION_PROVIDER=ollama
export SUMMARIZATION_MODEL=llama3.2

# 4. Initialize and start
brainpalace init
brainpalace start
brainpalace status
```

### Option B: Cloud Providers (Best Quality)

```bash
# 1. Install packages
pip install brainpalace-rag brainpalace-cli

# 2. Configure API keys
export OPENAI_API_KEY="sk-proj-..."       # For embeddings
export ANTHROPIC_API_KEY="sk-ant-..."     # For summarization (optional)

# 3. Initialize and start
brainpalace init
brainpalace start
brainpalace status
```

**Validation**: After each step, verify success before proceeding to the next.

---

## Setup Wizard

The canonical entry point for a complete guided setup is `/brainpalace-setup`. It asks all configuration questions interactively before running any CLI commands, then writes a comprehensive `config.yaml`.

### Wizard Configuration Questions

The wizard asks the following questions in sequence:

| Step | Question | Config Keys Set |
|------|----------|----------------|
| 2 | Embedding Provider | `embedding.provider`, `embedding.model`, optionally `embedding.base_url`, `embedding.api_key` or `embedding.api_key_env` |
| 3 | Summarization Provider | `summarization.provider`, `summarization.model`, optionally `summarization.base_url`, `summarization.api_key` or `summarization.api_key_env` |
| 4 | Storage Backend | `storage.backend` (`chroma` or `postgres`) |
| 5 | GraphRAG | `graphrag.enabled`, `graphrag.store_type`, `graphrag.use_code_metadata` |
| 6 | Default Query Mode | Written as YAML comment: `# query.default_mode` |

> **BM25 language is not a wizard step.** Set it via `brainpalace init --language <iso>` / `brainpalace folders add <path> --language <iso>`, or by editing the `bm25:` block in `config.yaml` directly — the config wizard does not ask about it.

> **Unified question set (init · install · config wizard).** `brainpalace init`
> (sparse PROJECT config) and `brainpalace install` / `brainpalace config wizard`
> (GLOBAL config) ask the **same project-config-backed questions**, so the
> front-ends never drift: embedding provider/model, summarizer provider/model,
> **reranker** (enabled), **embed-sessions** (`session_indexing.enabled` — billable
> opt-in, default OFF), **session-archive** (`session_indexing.archive.enabled` —
> free local backup of full raw transcripts incl. secrets, default ON),
> **git-history** (`git_indexing.enabled` + `depth`, default OFF), and **GraphRAG
> document extraction** (`graphrag.doc_extractor` = `langextract` | `none`).
> `init` additionally re-asks the per-project-overridable **reranker**
> (`reranker.enabled`) behind an *"inherited from global — change for this
> project? [y/N]"* gate, writing a **sparse override only when changed**;
> embedding/summarizer are not re-asked via that gate (they resolve via
> env-detection / global inheritance).

> **Opt-in optional-dep rule.** Enabling a feature whose "yes" needs an optional
> server extra triggers a download — **auto-installed on yes** (auto-detecting
> pipx → uv → pip), or the **exact install command is printed** if no manager is
> detected. Declining writes the disabling value (e.g. `graphrag.doc_extractor: none`)
> so the server's "not installed" warning never fires; optional deps are never
> auto-installed just because a feature is default-ON in code. Extras: GraphRAG
> doc-extraction → `langextract`; BM25 `lemma` engine → `simplemma`; postgres
> backend → `asyncpg` + `sqlalchemy`. `brainpalace doctor` reports optional-extra
> status for enabled features.

### Embedding Provider Options

| Option | Provider Key | Model | Notes |
|--------|-------------|-------|-------|
| Ollama (FREE, local) | `ollama` | `nomic-embed-text` | Requires Ollama running locally |
| OpenAI | `openai` | `text-embedding-3-large` | Requires `OPENAI_API_KEY` |
| Cohere | `cohere` | `embed-multilingual-v3.0` | Requires `COHERE_API_KEY`, multi-language support |
| Custom | (user-specified) | (user-specified) | Specify provider, model, and base_url |

### Summarization Provider Options

> **Provider is for CODE.** The summarization provider always summarizes your
> **CODE** during indexing (search quality). **Chat/session** summaries are a
> separate job, handled **FREE** by the Claude Code plugin. Without the plugin,
> chat summarization is **OFF by default** — the server-side provider distiller
> is doubly opt-in (`mode: provider`/`auto` **and** `SESSION_DISTILL_ENABLED=true`).

| Option | Provider Key | Model | Notes |
|--------|-------------|-------|-------|
| Ollama (FREE, local) | `ollama` | `llama3.2` | Requires Ollama running locally |
| Ollama + Mistral (FREE, local) | `ollama` | `mistral-small3.2` | Better summarization quality |
| Anthropic | `anthropic` | `claude-haiku-4-5-20251001` | Requires `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `gpt-4o-mini` | Requires `OPENAI_API_KEY` |
| Google Gemini | `gemini` | `gemini-3.1-flash-lite` (cheapest; premium e.g. `gemini-3.5-flash` or `gemini-3.1-pro-preview` can be set manually) | Requires `GOOGLE_API_KEY` |
| Grok (xAI) | `grok` | `grok-3-mini-fast` | Requires `XAI_API_KEY` |

### Config.yaml Written by Wizard

After answering all questions, the wizard writes a comprehensive `config.yaml` covering:
- `embedding.*` — provider, model, api_key or api_key_env, optional base_url
- `summarization.*` — provider, model, api_key or api_key_env, optional base_url
- `storage.*` — backend selection and (if PostgreSQL) connection settings
- `graphrag.*` — enabled flag, store_type, use_code_metadata
- `# query.default_mode` as a YAML comment (informational)

The file is chmod 600 automatically. A security warning is shown: never commit config.yaml to git.

**PostgreSQL + BM25**: When `storage.backend: "postgres"` is selected, the
disk-based BM25 index is replaced by PostgreSQL's built-in full-text search
(`tsvector` + `websearch_to_tsquery`). The `--mode bm25` command works
identically from the user's perspective. Language is configurable via
`storage.postgres.language` (default: `"english"`).

### Standalone Config Command

`/brainpalace-config` handles provider-specific details when called standalone (without the full wizard). It includes storage backend selection, indexing exclude patterns, and Ollama status checks.

---

## Prerequisites

### Required
- **Python 3.10+**: Verify with `python --version`
- **pip**: Python package manager

### Provider-Dependent
- **OpenAI API Key**: Required for OpenAI embeddings
- **Ollama**: Required for local/private deployments (no API key needed)

### System Requirements
- ~500MB RAM for typical document collections
- ~1GB RAM with GraphRAG enabled
- Disk space for ChromaDB vector store

---

## Installation

### Standard Installation

```bash
pip install brainpalace-rag brainpalace-cli
```

**Verify installation succeeded**:
```bash
brainpalace --version
```

Expected: Version number displayed (e.g., `3.0.0` or current version)

### With GraphRAG Support

```bash
pip install "brainpalace-rag[graphrag]" brainpalace-cli
```

### Enable GraphRAG (server)

```bash
export ENABLE_GRAPH_INDEX=true            # Master switch (default: true)
export GRAPH_STORE_TYPE=sqlite            # "sqlite" (default, persistent + temporal) or "simple" (in-memory)
export GRAPH_INDEX_PATH=./graph_index
export GRAPH_USE_CODE_METADATA=true       # Extract from AST metadata
export GRAPH_USE_LLM_EXTRACTION=true      # Use LLM extractor when available
export GRAPH_MAX_TRIPLETS_PER_CHUNK=10    # Triplet cap per chunk
export GRAPH_TRAVERSAL_DEPTH=2            # Default traversal depth
export GRAPH_EXTRACTION_MODEL=claude-haiku-4-5
```

Add the same values to your `.env` if you prefer file-based config.

### Virtual Environment (Recommended)

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install brainpalace-rag brainpalace-cli
```

### Installation Troubleshooting

| Problem | Solution |
|---------|----------|
| `pip not found` | Run `python -m ensurepip` |
| Permission denied | Use `pip install --user` or virtual env |
| Module not found after install | Restart terminal or activate venv |
| Wrong Python version | Use `python3.10 -m pip install` |

**Counter-example - Wrong approach**:
```bash
# DO NOT use sudo with pip
sudo pip install brainpalace-rag  # Wrong - creates permission issues
```

**Correct approach**:
```bash
pip install --user brainpalace-rag  # Correct - user installation
# OR use virtual environment
```

---

## Provider Configuration

BrainPalace supports pluggable providers with two configuration methods.

### Method 1: Configuration File (Recommended)

Create a `config.yaml` file in one of these locations:

1. `BRAINPALACE_CONFIG` env / project `./.brainpalace/config.yaml`
2. **XDG config (preferred global)**: `~/.config/brainpalace/config.yaml`
3. **User-level (legacy, deprecated)**: `~/.brainpalace/config.yaml`

```yaml
# ~/.config/brainpalace/config.yaml
server:
  url: "http://127.0.0.1:8000"
  port: 8000

project:
  state_dir: null  # null = use default (.brainpalace)

embedding:
  provider: "openai"
  model: "text-embedding-3-large"
  api_key: "sk-proj-..."  # Direct key, OR use api_key_env
  # api_key_env: "OPENAI_API_KEY"  # Read from env var

summarization:
  provider: "anthropic"
  model: "claude-haiku-4-5-20251001"
  api_key: "sk-ant-..."  # Direct key, OR use api_key_env
  # api_key_env: "ANTHROPIC_API_KEY"
```

**Config file search order**: BRAINPALACE_CONFIG env → current dir → project dir → XDG (~/.config/brainpalace/config.yaml) → legacy ~/.brainpalace (deprecated)

**Security**: If storing API keys in config file:
- Set file permissions: `chmod 600 ~/.config/brainpalace/config.yaml`
- Add to `.gitignore`: `config.yaml`
- Never commit API keys to version control

### Method 2: Environment Variables

Set variables in shell or `.env` file:

```bash
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-large
export SUMMARIZATION_PROVIDER=anthropic
export SUMMARIZATION_MODEL=claude-haiku-4-5-20251001
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Precedence order**: CLI options → environment variables → config file → defaults

---

### Provider Profiles

#### Fully Local with Ollama (No API Keys)

Best for privacy, air-gapped environments:

**Config file** (`~/.config/brainpalace/config.yaml`):
```yaml
embedding:
  provider: "ollama"
  model: "nomic-embed-text"
  base_url: "http://localhost:11434/v1"

summarization:
  provider: "ollama"
  model: "llama3.2"
  base_url: "http://localhost:11434/v1"
```

**Or environment variables**:
```bash
export EMBEDDING_PROVIDER=ollama
export EMBEDDING_MODEL=nomic-embed-text
export SUMMARIZATION_PROVIDER=ollama
export SUMMARIZATION_MODEL=llama3.2
```

**Prerequisite**: Ollama must be installed and running with models pulled.

#### Cloud (Best Quality)

**Config file**:
```yaml
embedding:
  provider: "openai"
  model: "text-embedding-3-large"
  api_key: "sk-proj-..."

summarization:
  provider: "anthropic"
  model: "claude-haiku-4-5-20251001"
  api_key: "sk-ant-..."
```

**Or environment variables**:
```bash
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

#### Mixed (Balance Quality and Privacy)

```yaml
embedding:
  provider: "openai"
  model: "text-embedding-3-large"
  api_key: "sk-proj-..."

summarization:
  provider: "ollama"
  model: "llama3.2"
```

### GraphRAG Configuration

GraphRAG enables graph-based entity-relationship extraction for advanced query modes.

**YAML config keys** (`config.yaml`):

```yaml
graphrag:
  enabled: true           # Master switch (default: true)
  store_type: "sqlite"    # "sqlite" (default, persistent + temporal) or "simple" (in-memory)
  use_code_metadata: true # Extract entities from AST metadata (imports, classes)
```

**`sqlite` is the default** and enables temporal validity (valid_from/valid_until edges,
point-in-time queries, decision supersession). `simple` disables all temporal features.

**Corresponding environment variables**:

| Env Var | Config Key | Default | Description |
|---------|-----------|---------|-------------|
| `ENABLE_GRAPH_INDEX` | `graphrag.enabled` | `true` | Master switch |
| `GRAPH_STORE_TYPE` | `graphrag.store_type` | `sqlite` | `simple` or `sqlite` |
| `GRAPH_USE_CODE_METADATA` | `graphrag.use_code_metadata` | `true` | AST metadata extraction |

**Note**: GraphRAG requires the `--include-code` flag during indexing to extract code structure:

```bash
brainpalace index ./src --include-code
```

The `sqlite` backend (default) is built into the stdlib — no optional extras needed.

### BM25 Language Configuration

BM25 keyword search uses language-aware stemming/lemmatization. Setting the correct project language improves retrieval quality for inflected languages (German, French, Spanish, Russian, etc.).

#### Set at Initialization

```bash
brainpalace init --language de              # German (Snowball stemmer)
brainpalace init --language fr             # French
brainpalace init --language es             # Spanish
brainpalace init --language ru             # Russian
brainpalace init --language hr --bm25-engine lemma  # Croatian (simplemma lemmatizer, hbs data)
```

For Croatian (`hr`) with `engine: lemma`, install the optional extra first:

```bash
pip install 'brainpalace[lemma-hr]'
```

#### Set via folders add

```bash
# Updates bm25.language project-wide (not per-folder)
brainpalace folders add ./docs --language de
```

#### YAML Config Block

```yaml
# .brainpalace/config.yaml
bm25:
  language: "en"               # ISO 639-1 project default (default: en)
  engine: "stem"               # stem (Snowball/PyStemmer) or lemma (simplemma)
  detect: false                # opt-in per-document language detection
  detect_min_confidence: 0.6   # confidence threshold for language detection (0–1)
```

#### BM25 Config Keys

| Key | Default | Description |
|-----|---------|-------------|
| `bm25.language` | `en` | ISO 639-1 project default language |
| `bm25.engine` | `stem` | `stem` (Snowball/PyStemmer, ~27 languages) or `lemma` (simplemma) |
| `bm25.detect` | `false` | Enable per-document automatic language detection |
| `bm25.detect_min_confidence` | `0.6` | Minimum detection confidence (0–1) |

#### Supported Languages

~27 Snowball/PyStemmer codes including: `en`, `de`, `fr`, `es`, `it`, `pt`, `nl`, `ru`, `sv`, `da`, `fi`, `no`, `hu`, `ro`, `tr`, plus a custom Croatian stemmer (`hr`). Unknown codes fall back to English tokenization.

#### Reindex After Language Change

Changing `bm25.language` or `bm25.engine` changes tokenization. The BM25 index auto-rebuilds from the stored corpus on the next server start (the analyzer fingerprint is persisted). To re-detect per-document languages when `bm25.detect: true`, re-run indexing:

```bash
brainpalace index ./docs
```

---

### Query Mode Selection

BrainPalace supports the following query modes, selectable per request with `--mode`:

| Mode | Description | Requirements |
|------|-------------|-------------|
| `hybrid` | Vector similarity + BM25 keyword (recommended default) | None |
| `semantic` | Pure vector similarity search | None |
| `bm25` | Keyword-only search (fast, no embedding needed) | None |
| `graph` | Entity relationship graph traversal | GraphRAG + ChromaDB backend |
| `multi` | Fuses vector + BM25 + graph with RRF | GraphRAG + ChromaDB backend |

**Note**: `graph` and `multi` modes are not available with PostgreSQL backend.
GraphRAG uses a graph store (sqlite default, simple opt-in) that is separate from the vector
store — it currently integrates only with ChromaDB.

**Per-request override**:

```bash
brainpalace query "authentication flow" --mode hybrid
brainpalace query "class relationships" --mode graph    # GraphRAG + ChromaDB required
brainpalace query "how do services work" --mode multi   # GraphRAG + ChromaDB required
```

**Note**: There is no global `query.default_mode` config key yet. Mode is per-request only. The setup wizard writes the selected default mode as a YAML comment for documentation purposes.

### Read-only mode (provider kill switch)

`brainpalace read-only on` sets `server.read_only: true` — the server makes no
outbound provider calls (embedding, summarization, remote rerank), indexing jobs
end `skipped`, startup self-heal recovers from cache only and skips its
destructive cleanup, and vector/hybrid queries fall back to BM25. `brainpalace
read-only off` restores normal operation; `brainpalace read-only status` reports
the effective value. Env override: `BRAINPALACE_READ_ONLY=true`. Requires a
server restart to take effect. Use it when the provider is unreachable (offline,
broken key, rate-limited) to keep the index queryable without risking data loss.

### Verify Configuration

```bash
brainpalace verify
```

**Counter-example - Common mistake**:
```bash
# DO NOT put keys in shell command history
OPENAI_API_KEY="sk-proj-abc123" brainpalace start  # Wrong - key in history
```

**Correct approaches**:
```bash
# Use config file (keys are in file, not command line)
brainpalace start

# Or use environment from shell profile
export OPENAI_API_KEY="sk-proj-..."  # In ~/.bashrc
brainpalace start
```

---

## Project Initialization

### Initialize Project

Navigate to the project root and run:

```bash
brainpalace init
```

**Verify initialization succeeded**:
```bash
ls .brainpalace/config.json
```

Expected: File exists

### Start Server

```bash
brainpalace start
```

**Verify server started**:
```bash
brainpalace status
```

Expected output:
```
Server Status: healthy
Port: 49321
Documents: 0
Mode: project
```

### Index Documents

```bash
brainpalace index ./docs
```

**Verify indexing succeeded**:
```bash
brainpalace status
```

Expected: Documents count > 0

### Test Search

```bash
brainpalace query "test query" --mode hybrid
```

Expected: Search results or "No results" (not an error)

---

## Verification

### Full Verification Checklist

Run each command and verify expected output:

- [ ] `brainpalace --version` shows version number (7.0.0+)
- [ ] `echo ${OPENAI_API_KEY:+SET}` shows "SET" (if using OpenAI)
- [ ] `ls .brainpalace/config.json` file exists
- [ ] `brainpalace status` shows "healthy"
- [ ] `brainpalace status` shows document count > 0
- [ ] `brainpalace query "test"` returns results or "no matches"
- [ ] `brainpalace folders list` shows indexed folders
- [ ] `brainpalace types list` shows file type presets
- [ ] `brainpalace jobs` shows job queue (empty or with history)

### GraphRAG Verification (if enabled)

- [ ] `echo ${ENABLE_GRAPH_INDEX}` shows "true"
- [ ] `brainpalace status --json | jq '.graph_index'` shows graph index info
- [ ] `brainpalace query "class relationships" --mode graph` returns results or graceful error
- [ ] `brainpalace query "how it works" --mode multi` returns fused results

### Automated Verification

```bash
brainpalace verify
```

This runs all checks and reports any issues.

### Post-Indexing Verification

After indexing documents, verify the pipeline is working:

```bash
# Monitor indexing job
brainpalace jobs --watch

# Check job completed successfully
brainpalace jobs <job_id>

# Verify incremental indexing works
brainpalace index ./docs  # Should show eviction summary with unchanged files

# Validate injection scripts before use
brainpalace inject ./docs --script enrich.py --dry-run
```

---

## When Not to Use

This skill focuses on **installation and configuration**. Do NOT use for:

- **Searching documents** - Use `using-brainpalace` skill instead
- **Query optimization** - Use `using-brainpalace` skill instead
- **Understanding search modes** - Use `using-brainpalace` skill instead
- **GraphRAG queries** - Use `using-brainpalace` skill instead

**Scope boundary**: Once BrainPalace is installed, configured, initialized, and verified healthy, switch to the `using-brainpalace` skill for search operations.

---

## Common Setup Issues

### Issue: Module Not Found

```bash
pip install --force-reinstall brainpalace-rag brainpalace-cli
```

### Issue: API Key Not Working

```bash
# Test OpenAI key
curl -s https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" | head -c 100
```

Expected: JSON response (not error)

### Issue: Server Won't Start

```bash
# Check for stale state
rm -f .brainpalace/runtime.json
rm -f .brainpalace/lock.json
brainpalace start
```

### Issue: Ollama Connection Failed

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags
```

Expected: JSON with model list

### Issue: No Search Results

```bash
brainpalace status  # Check document count
```

If count is 0, index documents:
```bash
brainpalace index ./docs
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BRAINPALACE_CONFIG` | No | - | Path to config.yaml file |
| `BRAINPALACE_URL` | No | `http://127.0.0.1:8000` | Server URL for CLI |
| `BRAINPALACE_STATE_DIR` | No | `.brainpalace` | State directory path |
| `EMBEDDING_PROVIDER` | No | `openai` | Provider: openai, cohere, ollama |
| `EMBEDDING_MODEL` | No | `text-embedding-3-large` | Model name |
| `SUMMARIZATION_PROVIDER` | No | `anthropic` | Provider: anthropic, openai, gemini, grok, ollama |
| `SUMMARIZATION_MODEL` | No | `claude-haiku-4-5-20251001` | Model name |
| `OPENAI_API_KEY` | Conditional | - | Required if using OpenAI |
| `ANTHROPIC_API_KEY` | Conditional | - | Required if using Anthropic |
| `GOOGLE_API_KEY` | Conditional | - | Required if using Gemini |
| `XAI_API_KEY` | Conditional | - | Required if using Grok |
| `COHERE_API_KEY` | Conditional | - | Required if using Cohere |
| `EMBEDDING_CACHE_MAX_MEM_ENTRIES` | No | 1000 | Max in-memory LRU entries (~12 MB at 3072 dims per 1000 entries) |
| `EMBEDDING_CACHE_MAX_DISK_MB` | No | 500 | Max disk size for the SQLite embedding cache |

**Note**: Environment variables override config file values. Config file values override defaults.

### Caching

#### Embedding Cache

The embedding cache is **automatic** — no setup required. Embeddings are cached on first compute
and reused on subsequent reindexes of unchanged content, significantly reducing OpenAI API costs
when using file watching or frequent reindexing.

The two cache env vars allow tuning for specific environments:
- **Large indexes** — increase `EMBEDDING_CACHE_MAX_MEM_ENTRIES` (e.g., 5000) to keep more embeddings
  in the fast in-memory tier and reduce SQLite lookups
- **Memory-constrained environments** — decrease `EMBEDDING_CACHE_MAX_MEM_ENTRIES` (e.g., 200) to
  limit RAM usage; the disk cache still provides cost savings even with a small memory tier
- **Disk space constrained** — decrease `EMBEDDING_CACHE_MAX_DISK_MB` (e.g., 100) to cap the SQLite
  cache database size; oldest entries are evicted when the limit is reached

The disk cache uses SQLite with WAL mode for safe concurrent access during indexing operations.

#### Query Cache

The query cache is **automatic** — no setup required. Identical queries within
the TTL window return instantly without hitting storage.

- **`graph` and `multi` modes bypass the cache** — each call reaches storage
  for fresh results.
- Cache is **invalidated on every completed reindex job** (file watcher or manual).
- Configurable via environment variables (see Configuration Guide for details):
  - `QUERY_CACHE_TTL` — cache TTL in seconds (default: 300, i.e., 5 minutes)
  - `QUERY_CACHE_MAX_SIZE` — max cached query results (default: 256)

---

## Reference Documentation

| Guide | Description |
|-------|-------------|
| [Configuration Guide](references/configuration-guide.md) | Config file format and locations |
| [Installation Guide](references/installation-guide.md) | Detailed installation options |
| [Provider Configuration](references/provider-configuration.md) | All provider settings |
| [Troubleshooting Guide](references/troubleshooting-guide.md) | Extended issue resolution |

---

## Support

- Issues: https://github.com/bxw91/brainpalace/issues
- Documentation: Reference guides in this skill

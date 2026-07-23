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
  - name: global
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
  - name: defer-activation
    type: bool
    required: false
    default: false
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
  - name: mcp
    type: bool
    required: false
    default: true
  - name: sessions
    type: bool
    required: false
    default: ""
  - name: archive
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
  - name: doc-weight
    type: float range
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
  - name: folder
    type: directory
    required: false
    default: ""
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-07-23
---

# Initialize BrainPalace Project

## Purpose

Initializes the current project for BrainPalace by creating the necessary configuration directory and files. This sets up per-project isolation, allowing each project to have its own BrainPalace instance with separate configuration and data.

> **Plugin flow = configure, then YOU start it.** When run through the plugin,
> init uses `--defer-activation`: it writes config but does **not** start the
> server or index anything, and it arms a one-shot activation marker
> (`cli.await_first_start`). While that marker is set, passive vectors (the
> SessionStart hook, MCP `--ensure-server`) will **not** auto-start the project —
> so a freshly-configured project stays quiet until you review it and start it
> the first time yourself: `brainpalace start` (or the dashboard Instances →
> Start). That manual start clears the marker; from then on it autostarts
> normally. (A bare terminal `brainpalace init`, with no flag, keeps the old
> behavior: start + index immediately.)

> **Interactive flow — expand-on-ON grid.** A non-`--yes` `brainpalace init` opens
> **directly on the review grid**, values resolved from `global < code` plus the
> detected provider. Each division is a single line — `N. Label : field = value |
> field = value | …` — listing **every** visible field of an **ON** (its
> enable/mode gate active) or pure-config division — secrets included, shown in full
> (the terminal is trusted) — and collapsing a toggleable **OFF** division to its
> gate value. Empty fields are omitted, and a selector-dependent field shows only
> when its selector is active (e.g. `storage.postgres` only under
> `backend = postgres`). Section descriptions show **only when you drill in to
> edit**, not in the overview. Edit by division number or `[A]ll`; drilling a
> division edits **all** its fields, asking the enable/mode gate first and skipping
> a sub-block when its gate is OFF. `[C]ontinue` accepts. Billable/secret consent
> fields (embed-sessions, git-history, graphrag-extraction) prompt with their
> warning **only when you edit them**, and opt-in billable fields stay **OFF** if
> you accept without touching them — no silent spend. Section names/descriptions
> are single-sourced with the web dashboard.
> `--yes` / `--json` / non-TTY runs skip the grid and apply the resolved defaults.

> **Index-target picker (asked first).** On a fresh interactive run that will index
> (starts + watches), `init` asks **before** the review grid: which folder to index
> — type a path relative to the project root, or press Enter to keep the **whole
> project** (today's default) — and its index type (**code + docs**, or **docs
> only**). These populate the same targets the `-F/--folder` and
> `--include-code/--no-code` flags feed, so the token estimate, provider preflight,
> and first index all target your choice. Passing `-F` or `--include-code/--no-code`
> explicitly suppresses the matching prompt; `--yes`/`--json`/`--no-start` skip the
> picker entirely.

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
| --defer-activation / --plugin-managed | No | false | Configure but leave NOT running: implies `--no-start --no-watch` and arms the `cli.await_first_start` gate so passive vectors don't auto-start it until you start it once. Used by the plugin path; an explicit `--start` overrides it; no effect on an already-started project. |
| --watch | No | auto (when starting) | Folder watch mode: `auto` (index + watch) or `off` |
| --no-watch | No | false | Do not register/watch the project folder |
| --yes / -y | No | false | Skip the confirmation prompt and apply defaults |
| --sessions / --no-sessions | No | off (default/--yes do NOT embed) | INDEX this project's AI chat transcripts (billable); pass `--sessions` to enable |
| --archive / --no-archive | No | on | ARCHIVE raw transcripts under `.brainpalace/` (free, independent of indexing) |
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

> **Pre-index token estimate + ignore-loop (opt-in).** On an interactive run,
> before the first index `init` asks whether to estimate approximate
> embedding-token usage (default **yes**, never shown under `--json`/CI). The
> estimate uses the same file-selection rules **and the same
> `--include-code`/`--no-code` scope** as the real index, and reflects your
> chosen embedding provider's tokenizer. It prints a per-top-level-folder
> breakdown (files · code tokens · doc tokens, alphabetical, `(root files)`
> pinned last), then a menu: **add** or **remove** a file/folder/glob from
> what gets indexed — saved to BrainPalace config (`indexing.exclude_patterns`,
> sparse, extends the built-in defaults) or to `.gitignore` (written
> immediately, **permanent** — undo only by hand-editing `.gitignore` later);
> **reset** the BrainPalace ignore list back to its pre-init state;
> **re-estimate** to refresh the numbers after an edit; **proceed**; or
> **cancel** (rolls back a config this `init` created). Proceeding with an
> empty resulting index is blocked. Run the estimate anytime with
> `brainpalace index <path> --estimate`.

## Execution

### Run Initialization

```bash
# Plugin path: configure only, leave it NOT running (you start it yourself).
brainpalace init --defer-activation
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

Config saved — the server is NOT running, and it will not auto-start until you
start it once. Review the config and start it the first time yourself:

Next steps:
  1. Review config: /brainpalace:brainpalace-config (or `brainpalace config show`)
  2. Start server (first time, by you): /brainpalace:brainpalace-start
  3. Index documents: /brainpalace:brainpalace-index ./docs
  4. Search: /brainpalace:brainpalace-search "your query"
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
| --host | text | "" | Server bind host. Default: inherit from global config / code (127.0.0.1). Pass to override for this project (writes bind.bind_host to config.yaml). |
| --port | integer | "" | Preferred server port (default: auto-select from range) |
| --force | bool | false | Overwrite existing configuration |
| --global | bool | false | Edit the global ~/.config/brainpalace/config.yaml (XDG) that all projects inherit, through the same review screen. No project index/start. |
| --json | bool | false | Output as JSON |
| --state-dir | directory | "" | Custom state directory for index data (default: .brainpalace) |
| --force-monorepo-root | bool | false | Allow init at a directory whose CLAUDE.md flags it as a mono-repo workspace root. Use only if you really want a project-level state dir at the workspace root. |
| --start | bool | "" | Start the server after init. Default: ON in an interactive terminal (after a confirmation) or with --yes; OFF in non-interactive/--json runs. --no-start forces config-only. |
| --defer-activation | bool | false | Configure the project but leave it NOT running: implies --no-start and --no-watch, and writes a one-shot activation marker (cli.await_first_start) so passive vectors (the SessionStart hook, MCP --ensure-server) do NOT auto-start it until the user starts it once (`brainpalace start` or the dashboard Start). Used by the plugin setup path. An explicit --start overrides it. No effect on an already-started project. |
| --watch | choice | "" | Folder watch mode when starting (auto = register + index project_root + live re-index). Default 'auto' when starting, else 'off'. |
| --no-watch | bool | false | Do not register/watch the project folder (alias for --watch off). |
| --yes | bool | false | Skip the confirmation prompt and apply the full resolved plan. |
| --mcp | bool | true | Write BrainPalace's MCP server into the project's .mcp.json (merged, never clobbering other servers already declared there). ON by default — unlike session embedding, this costs no money, only ~2,360 tokens of context in a project that already runs BrainPalace. Pass --no-mcp to opt out. Written on every init path, including --defer-activation: .mcp.json is configuration, not activation, so it starts nothing. Tools appear next session, after you approve the project's MCP servers. |
| --sessions | bool | "" | INDEX this project's AI chat transcripts into searchable session memory (embeddings, billable). ON by default for new projects: interactive runs confirm (default yes), non-interactive runs enable it. Pass --no-sessions to opt out (archive still runs). |
| --archive | bool | "" | ARCHIVE raw transcripts under .brainpalace/ as a durable backup (no embeddings, independent of indexing). ON by default. Pass --no-archive to opt out. |
| --extract | bool | "" | SUMMARIZE each session into durable knowledge (summary, decisions, triplets). ON by default, summarized ONLY inside Claude Code (the plugin, free on your Claude Code subscription — no separate API bill). The server does not summarize on its own. Pass --no-extract to opt out. |
| --git-history | bool | "" | INDEX this repo's git commit history (message + diff stat) as searchable chunks. OFF by default — commits can contain secrets, so this is a deliberate opt-in. Interactive runs ask (default no). |
| --graphrag-extract | bool | "" | Extract a knowledge graph from document text (LLM triplet extraction via extraction.mode). |
| --migrate-graph-store | bool | "" | On an already-initialized project whose graph store is the legacy in-memory 'simple' backend, upgrade graphrag.store_type to 'sqlite' (persistent + temporal; the existing graph is replayed into sqlite on next start, with the JSON kept for rollback). Interactive runs ask (default yes). No effect on fresh inits or projects already on sqlite. |
| --language | text | "" | Project default natural language for BM25 indexing (ISO 639-1, e.g. en, de, hr). Passed → written to bm25.language; omitted → inherit from global config / code default (en). |
| --reranking | bool | "" | Two-stage reranking: a local cross-encoder re-scores the top candidates for finer relevance ordering. OFF by default — the local model needs the heavy reranker-local extra (~2.8 GB PyTorch). --reranking installs that extra and enables it; or set reranker.provider=ollama for a torch-free reranker. Writes reranker.enabled to config.yaml. |
| --doc-weight | float range | "" | Trust of docs vs code in search (0.0=exclude … 0.5=default … 1.0=equal). Writes ranking.doc_weight to config.yaml non-interactively (the field is also editable in the review grid's Retrieval Ranking division). |
| --bm25-engine | choice | "" | BM25 stemming engine: 'stem' (Snowball, no extra deps) or 'lemma' (simplemma, better recall for morphologically-rich languages). Passed → written to bm25.engine; omitted → inherit from global config / code default (stem). engine=lemma requires simplemma: pip install 'brainpalace[lemma-hr]'. |
| --include-code | bool | true | Index source code files alongside documents (default: ON). Use --no-code for doc-only repos. Applies to the first index and to the pre-index token estimate. |
| --folder | directory | "" | Register + index ONLY this folder at start (repeatable), instead of the whole project root. Paths outside the project tree are allowed. Implies watching the given folders; incompatible with --no-watch/--watch off. |
<!--/GENERATED-->

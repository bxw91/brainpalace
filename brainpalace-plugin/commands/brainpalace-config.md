---
name: brainpalace-config
description: Configure all BrainPalace settings interactively via the unified registry-driven editor — providers, storage, GraphRAG, reranking, sessions, git-history, and more
parameters: []
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-06-28
---

# Configure BrainPalace

## Purpose

`brainpalace init` is the **single config editor** for all BrainPalace settings.
It branches on project state:

- **Fresh project** — an interactive run opens **directly on the review grid**,
  values resolved from `global < code` plus the detected provider. The grid
  **expands on ON**: each division is one line (`N. Label : field = value | …`)
  listing every non-empty visible field of an ON or pure-config division (secrets
  included), collapsing a toggleable OFF division to its gate value; empty fields
  are omitted and a selector-dependent field (e.g. `storage.postgres`) shows only
  when its selector is active; descriptions show only when you drill in to edit.
  Edit by division
  number / `[A]ll` (drilling edits all of a division's fields, gate asked first),
  then `[C]ontinue` accepts → token estimate → optional server start.
  Billable/secret consent fields (sessions, git-history, extraction) prompt with
  their warning only when you edit them; the previous linear question sequence is
  gone.
- **Already-initialized project** — drops directly into the review editor so you
  can change any config field without re-running the full setup.
- **`init --global`** — edits the machine-wide XDG config
  (`~/.config/brainpalace/config.yaml`); no project root required.

`brainpalace config wizard` (and `wizard --global`) is a **back-compat alias**
of `brainpalace init` (`init --global`). The bespoke 12-step wizard prompt flow
has been replaced by the unified review editor.

> **Review grid UX — expand-on-ON.** An interactive `init` opens **directly on the
> grid** over every config division (Embedding, Summarization, Reranker, Storage,
> GraphRAG, Query Log, BM25, Git Indexing, Session Vector Indexing, Session
> Summarization, Extraction Engine, Compute, Usage Metrics), values resolved from
> `global < code` plus the detected provider. Each division is a single line
> (`N. Label : field = value | …`): an **ON** or pure-config division lists
> **every** visible field (secrets shown in full — terminal-trusted; empty renders
> `()`, booleans `on`/`off`); a toggleable **OFF** division collapses to its gate
> value. Section descriptions show only when you drill in to edit. Type a **division
> number** to drill in and edit
> **all** its fields (the enable/mode gate is asked first; a sub-block whose gate is
> OFF is skipped), **`A`** to walk every division, **`C`** to accept (writes nothing
> if unchanged — sparse invariant), or **`E`** to cancel. Billable/secret consent
> fields are never plain-prompted — they prompt with their warning **only when you
> drill into their division**, and opt-in billable fields stay **OFF** if you accept
> the grid without touching them. Section names/descriptions are single-sourced with
> the web dashboard.
>
> **Single source.** Fields, labels, help text, and enum choices all derive from
> the CLI field registry (`config_fields.py`). The review screen, the dashboard
> Config tab, and the consent block share the same registry — the three
> front-ends cannot drift.
>
> **Global-only:** `init --global` (or `wizard --global`) additionally prompts
> the web-dashboard control-plane settings — **autostart** (`dashboard.autostart`,
> default ON) and **dashboard port** (`dashboard.port`, default 8787) — written
> to the `dashboard:` block of the XDG config. These are NOT asked per-project.
> `dashboard.*` is a **separate fleet-wide surface** (dashboard Settings tab +
> this CLI step); it is NOT part of the per-project config registry and does NOT
> appear in the Config/Global Config tabs.
>
> **Per-field scope:** `init --global`'s CLI review screen shows all registry
> fields except project-scoped ones (e.g.
> `session_indexing.archive.dir` — a project-relative path). When editing a
> project layer, fields inherited from the global config are marked
> **"inherited from global"** so you know which overrides are project-specific.

## Usage

```
/brainpalace:brainpalace-config
```

## Execution

### Step 1: Detect Config File Location

**IMPORTANT: Check BOTH locations and edit the correct one.**

Config file search order (highest to lowest):
1. **BRAINPALACE_CONFIG** environment variable
2. **State directory**: `BRAINPALACE_STATE_DIR/config.yaml`
3. **Current directory**: `./config.yaml`
4. **Project-level** (walk up from CWD): `./.brainpalace/config.yaml`
5. **XDG config** (preferred user-level): `~/.config/brainpalace/config.yaml`
6. **Legacy user-level** (deprecated): `~/.brainpalace/config.yaml`

Use `brainpalace config path` to see which file is active.

```bash
# Check which config file is active
brainpalace config path

# Show the full active configuration
brainpalace config show
```

**When editing config: Use the file reported by `brainpalace config path`. Project-level takes precedence over user-level.**

### Step 2: Run Pre-Flight Detection

Run the environment detection script once. It consolidates Ollama check, Docker check, large-dir scan, and config detection into a single call:

```bash
# Find the script — adjust path if plugin is installed to ~/.claude/plugins/
SCRIPT=$(find ~/.claude/plugins/brainpalace/scripts ~/.claude/skills/brainpalace/scripts brainpalace-plugin/scripts -name "bp-setup-check.sh" 2>/dev/null | head -1)
if [ -n "$SCRIPT" ]; then
  SETUP_STATE=$("$SCRIPT")
  echo "$SETUP_STATE"
else
  echo "bp-setup-check.sh not found — run detection manually (see fallback below)"
  SETUP_STATE="{}"
fi
```

Parse the JSON output into local variables for use in subsequent steps:

```bash
OLLAMA_RUNNING=$(echo "$SETUP_STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ollama_running','false'))" 2>/dev/null || echo "false")
CONFIG_FILE=$(echo "$SETUP_STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('config_file_path',''))" 2>/dev/null || echo "")
DOCKER_AVAILABLE=$(echo "$SETUP_STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('docker_available','false'))" 2>/dev/null || echo "false")
AVAILABLE_PORT=$(echo "$SETUP_STATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('available_postgres_port','5432'))" 2>/dev/null || echo "5432")
```

**Interpreting results:**
- `ollama_running: true` → Ollama IS running; proceed with configuration
- `ollama_running: false` → Tell user to start Ollama: `ollama serve`
- `docker_available: true` → Docker is installed; PostgreSQL setup is possible
- `config_file_path: "..."` → Edit THAT config file (project-level takes priority)

**Fallback (if bp-setup-check.sh not found):** Use the manual methods below — but `bp-setup-check.sh` should always be present if the plugin is installed.

<details>
<summary>Manual fallback (not needed when plugin is installed)</summary>

```bash
# Manual Ollama check
curl -s --connect-timeout 3 http://localhost:11434/ 2>/dev/null
lsof -i :11434 2>/dev/null | head -3
ollama list 2>/dev/null | head -10
```

</details>

### Step 3: Use AskUserQuestion for Provider Selection

> **Summarization provider is for CODE.** It always makes short LLM summaries of
> your **CODE** during indexing (search quality). **Chat/session** summaries are
> a separate job, handled **FREE** by the Claude Code plugin. Without the plugin,
> chat summarization is **OFF by default** — the server-side provider distiller
> is doubly opt-in (`mode: provider`/`auto` **and** `SESSION_DISTILL_ENABLED=true`).

```
Which provider setup would you like for BrainPalace?

Options:
1. Ollama (Local) - FREE, no API keys required. Uses nomic-embed-text + llama3.2
2. OpenAI + Anthropic - Best quality cloud providers. Requires OPENAI_API_KEY and ANTHROPIC_API_KEY
3. Google Gemini - Google's models. Requires GEMINI_API_KEY
4. Custom Mix - Choose different providers for embedding vs summarization
5. Ollama + Mistral - FREE, uses nomic-embed-text + mistral-small3.2 (better summarization)
```

### Step 4: Based on Selection

**For Ollama (Option 1):**

```
=== Ollama Setup (Local, Free) ===

Ollama runs locally - no API keys or cloud costs!

1. Install Ollama (if not installed):

   macOS:   brew install ollama
   Linux:   curl -fsSL https://ollama.com/install.sh | sh
   Windows: Download from https://ollama.com/download

2. Start Ollama server:
   ollama serve

3. Pull required models:
   ollama pull nomic-embed-text      # For embeddings (8192 token context)
   ollama pull llama3.2              # For summarization

   IMPORTANT: Use nomic-embed-text (NOT mxbai-embed-large)
   - nomic-embed-text: 8192 token context - handles large documents
   - mxbai-embed-large: only 512 token context - causes indexing errors

4. Create config file (~/.config/brainpalace/config.yaml):

   mkdir -p ~/.config/brainpalace
   cat > ~/.config/brainpalace/config.yaml << 'EOF'
   embedding:
     provider: "ollama"
     model: "nomic-embed-text"
     base_url: "http://localhost:11434/v1"

   summarization:
     provider: "ollama"
     model: "llama3.2"
     base_url: "http://localhost:11434/v1"
   EOF

   OR use environment variables:
   export EMBEDDING_PROVIDER=ollama
   export EMBEDDING_MODEL=nomic-embed-text
   export SUMMARIZATION_PROVIDER=ollama
   export SUMMARIZATION_MODEL=llama3.2

5. Ollama performance tuning (optional — only relevant when embedding provider is Ollama):

   EMBEDDING_BATCH_SIZE=10       # default batch size; reduce if Ollama runs out of memory
   OLLAMA_REQUEST_DELAY_MS=0     # add delay (ms) between batches if Ollama is overwhelmed

   These can be added to .env in the brainpalace-server directory or set as env vars.

6. Start BrainPalace:
   /brainpalace:brainpalace-start

No API keys needed!
```

**For OpenAI + Anthropic (Option 2):**

```
=== Cloud Provider Setup ===

1. Get API keys:
   - OpenAI: https://platform.openai.com/account/api-keys
   - Anthropic: https://console.anthropic.com/

2. Create config file (~/.config/brainpalace/config.yaml):

   mkdir -p ~/.config/brainpalace
   cat > ~/.config/brainpalace/config.yaml << 'EOF'
   embedding:
     provider: "openai"
     model: "text-embedding-3-large"
     api_key: "sk-proj-YOUR-KEY-HERE"

   summarization:
     provider: "anthropic"
     model: "claude-haiku-4-5-20251001"
     api_key: "sk-ant-YOUR-KEY-HERE"
   EOF

   chmod 600 ~/.config/brainpalace/config.yaml  # Secure the file

   OR use environment variables:
   export OPENAI_API_KEY="sk-proj-..."
   export ANTHROPIC_API_KEY="sk-ant-..."

3. Start BrainPalace:
   /brainpalace:brainpalace-start
```

**For Gemini (Option 3):**

```
=== Google Gemini Setup ===

1. Get key: https://aistudio.google.com/apikey
2. Set: export GEMINI_API_KEY="AIza..."

Create config file (~/.config/brainpalace/config.yaml):

  mkdir -p ~/.config/brainpalace
  cat > ~/.config/brainpalace/config.yaml << 'EOF'
  embedding:
    provider: "gemini"
    model: "text-embedding-004"
    api_key: "AIza..."

  summarization:
    provider: "gemini"
    model: "gemini-3.1-flash-lite"
    api_key: "AIza..."
  EOF

  chmod 600 ~/.config/brainpalace/config.yaml  # Secure the file

OR use environment variables:
export EMBEDDING_PROVIDER=gemini
export EMBEDDING_MODEL=text-embedding-004
export SUMMARIZATION_PROVIDER=gemini
export SUMMARIZATION_MODEL=gemini-3.1-flash-lite
export GEMINI_API_KEY="AIza..."
```

**For Custom Mix (Option 4):**

Redirect to: `/brainpalace:brainpalace-providers switch`

**For Ollama + Mistral (Option 5):**

```
=== Ollama + Mistral Setup (Local, Free) ===

Uses Mistral's small model for better summarization quality.

1. Ensure Ollama is running:
   ollama serve

2. Pull required models:
   ollama pull nomic-embed-text           # For embeddings (8192 token context)
   ollama pull mistral-small3.2:latest    # For summarization (better quality)

3. Create config file (~/.config/brainpalace/config.yaml):

   mkdir -p ~/.config/brainpalace
   cat > ~/.config/brainpalace/config.yaml << 'EOF'
   embedding:
     provider: "ollama"
     model: "nomic-embed-text"
     base_url: "http://localhost:11434/v1"

   summarization:
     provider: "ollama"
     model: "mistral-small3.2:latest"
     base_url: "http://localhost:11434/v1"
   EOF

   OR use environment variables:
   export EMBEDDING_PROVIDER=ollama
   export EMBEDDING_MODEL=nomic-embed-text
   export SUMMARIZATION_PROVIDER=ollama
   export SUMMARIZATION_MODEL=mistral-small3.2:latest

4. Start BrainPalace:
   /brainpalace:brainpalace-start

No API keys needed! Mistral-small3.2 provides better summarization than llama3.2.
```

## Output

### Initial Status Display

```
BrainPalace Configuration
=========================

Current Configuration:
  Embedding:      ollama / nomic-embed-text
  Summarization:  ollama / llama3.2

Provider Options:
-----------------

1. OLLAMA (Local, Free)
   - No API keys required
   - Runs on your machine
   - Models: nomic-embed-text, llama3.2
   - Setup: ollama serve

2. OPENAI + ANTHROPIC (Cloud)
   - Best quality embeddings and summaries
   - Requires: OPENAI_API_KEY, ANTHROPIC_API_KEY
   - Models: text-embedding-3-large, claude-haiku

3. GOOGLE GEMINI (Cloud)
   - Google's models (summarization only — Gemini embeddings are not supported)
   - Requires: GEMINI_API_KEY
   - Models: gemini-3.1-flash-lite (summarization)

4. CUSTOM MIX
   - Choose different providers for each function
   - Run: /brainpalace:brainpalace-providers switch

5. OLLAMA + MISTRAL (Local, Free)
   - Better summarization than llama3.2
   - Models: nomic-embed-text, mistral-small3.2

Which setup would you like? (Enter 1-5)
```

### Ollama Setup Complete

```
Ollama Configuration Complete!
==============================

Config file created: ~/.config/brainpalace/config.yaml

  embedding:
    provider: "ollama"
    model: "nomic-embed-text"
    base_url: "http://localhost:11434/v1"

  summarization:
    provider: "ollama"
    model: "llama3.2"
    base_url: "http://localhost:11434/v1"

(Or if using environment variables):
  EMBEDDING_PROVIDER=ollama
  EMBEDDING_MODEL=nomic-embed-text
  SUMMARIZATION_PROVIDER=ollama
  SUMMARIZATION_MODEL=llama3.2

Next steps:
1. Ensure Ollama is running: ollama serve
2. Initialize project: /brainpalace:brainpalace-init
3. Start server: /brainpalace:brainpalace-start
```

**Note:** Configuration is loaded once at server startup. After changing
`config.yaml` or environment variables, restart the server for changes to
take effect:

```
brainpalace stop && brainpalace start
```

## Error Handling

### Ollama Not Installed

```
Ollama not found. Install with:

macOS:   brew install ollama
Linux:   curl -fsSL https://ollama.com/install.sh | sh
Windows: https://ollama.com/download
```

### Ollama Not Running

```
Ollama is installed but not running.

Start it with: ollama serve

Then pull models:
  ollama pull nomic-embed-text
  ollama pull llama3.2
```

### Missing API Key for Cloud Provider

```
Cloud provider selected but API key not set.

For OpenAI:    export OPENAI_API_KEY="sk-proj-..."
For Anthropic: export ANTHROPIC_API_KEY="sk-ant-..."
For Google:    export GEMINI_API_KEY="AIza..."
For xAI:       export XAI_API_KEY="xai-..."
```

## Security Guidance

**For cloud providers:**
- Never commit API keys to version control
- Add `config.yaml` and `.env` files to `.gitignore`
- If storing API keys in config files, restrict permissions:
  ```bash
  chmod 600 ~/.config/brainpalace/config.yaml
  ```
- Use `api_key_env` in config to read from env vars instead of storing directly

**For Ollama:**
- Runs locally - no keys to manage
- Data stays on your machine

## Step 5: Select Storage Backend (ChromaDB or PostgreSQL)

After provider configuration, confirm which storage backend to use for indexing and search.

### AskUserQuestion: Storage Backend Selection

```
Which storage backend would you like to use?

Options:
1. ChromaDB (Default) - Local-first, zero ops, best for small to medium projects
2. PostgreSQL + pgvector - Best for larger datasets, requires a running database
```

### Backend Resolution Order

BrainPalace resolves the storage backend in this order:
1. `BRAINPALACE_STORAGE_BACKEND` environment variable (highest priority)
2. `storage.backend` in config.yaml
3. Default: `chroma`

### PostgreSQL Port Auto-Discovery

When the user selects PostgreSQL, automatically find an available port before writing config:

```bash
# Scan for a free port in the PostgreSQL range
POSTGRES_PORT=""
for port in $(seq 5432 5442); do
  if ! lsof -i :$port -sTCP:LISTEN >/dev/null 2>&1; then
    POSTGRES_PORT=$port
    echo "Found available port: $port"
    break
  else
    echo "Port $port in use, trying next..."
  fi
done

if [ -z "$POSTGRES_PORT" ]; then
  echo "ERROR: No available ports in range 5432-5442"
  echo "Free a port or configure storage.postgres.port manually."
  exit 1
fi
echo "PostgreSQL will use port: $POSTGRES_PORT"
```

Use this discovered port in BOTH the Docker Compose command AND config.yaml.

### YAML Configuration (PostgreSQL Example)

If the user selects PostgreSQL, add the `storage.backend` selection plus a full `storage.postgres` block.
**Use the auto-discovered port from the scan above** (not a hardcoded 5432):

```yaml
storage:
  backend: "postgres"  # or "chroma"
  postgres:
    host: "localhost"
    port: <DISCOVERED_PORT>  # e.g., 5433 if 5432 was in use
    database: "brainpalace"
    user: "brainpalace"
    password: "brainpalace_dev"
    pool_size: 10
    pool_max_overflow: 10
    language: "english"
    hnsw_m: 16
    hnsw_ef_construction: 64
    debug: false
```

Start the PostgreSQL container on the same discovered port:

```bash
POSTGRES_PORT=$POSTGRES_PORT docker compose -f <plugin_path>/templates/docker-compose.postgres.yml up -d
```

**Important notes:**
- `DATABASE_URL` overrides only the PostgreSQL connection string. Pool sizing and HNSW tuning still come from `storage.postgres`.
- There is no automatic migration between backends. Switching backends requires re-indexing your documents.
- The port auto-discovery ensures no conflicts with existing PostgreSQL instances on the host.

If the user selects ChromaDB, you can omit `storage.postgres` entirely and leave `storage.backend` as `chroma` (or omit it to use the default).

## Step 6: Configure Indexing Excludes

After provider setup, help the user configure which directories to exclude from indexing.

### Detect Large Directories

The pre-flight detection from Step 2 already scanned for large directories. Parse the results:

```bash
echo "$SETUP_STATE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
dirs = d.get('large_dirs', [])
if dirs:
    print('Large directories found — consider excluding these:')
    for entry in dirs:
        print(f'  {entry[\"path\"]}/ - {entry[\"size\"]} ({entry[\"file_count\"]} files) — SHOULD EXCLUDE')
else:
    print('No large directories detected in current directory')
"
```

### Show Current Exclude Patterns

```bash
echo "=== Current Exclude Patterns ==="
if [ -f ".brainpalace/config.json" ]; then
  cat .brainpalace/config.json | grep -A20 '"exclude_patterns"'
else
  echo "Using defaults: node_modules, __pycache__, .venv, venv, .git, dist, build, target"
fi
```

### Ask User About Additional Excludes

Use AskUserQuestion:

```
Based on the scan above, would you like to:

Options:
1. Use defaults (node_modules, .venv, __pycache__, .git, dist, build, target)
2. Add custom exclude patterns
3. Skip - I'll configure manually later
```

**If Option 2 (Custom):**

Ask the user which additional directories to exclude, then update `.brainpalace/config.json`:

```bash
# Example: Add custom exclude pattern
# Read current config, add pattern, write back
cat .brainpalace/config.json | jq '.exclude_patterns += ["**/my-custom-dir/**"]' > /tmp/config.json && mv /tmp/config.json .brainpalace/config.json
```

### Default Exclude Patterns

These are excluded by default (no config needed):

| Pattern | Description |
|---------|-------------|
| `**/node_modules/**` | JavaScript/Node.js dependencies |
| `**/.venv/**` | Python virtual environments |
| `**/venv/**` | Python virtual environments |
| `**/__pycache__/**` | Python bytecode cache |
| `**/.git/**` | Git repository data |
| `**/dist/**` | Build output |
| `**/build/**` | Build output |
| `**/target/**` | Rust/Java build output |
| `**/.next/**` | Next.js build cache |
| `**/.nuxt/**` | Nuxt.js build cache |
| `**/coverage/**` | Test coverage reports |

## Step 7: Configure GraphRAG (Knowledge Graph)

After storage backend selection, ask whether to enable graph indexing.

### AskUserQuestion: GraphRAG Selection

```
Would you like to enable GraphRAG (knowledge graph indexing)?

GraphRAG extracts entity relationships from your documents and code, enabling
graph-based queries like "what classes depend on X?" alongside standard search.

Options:
1. Disabled (Default) - Standard vector + BM25 hybrid search only
2. AST + LangExtract (Recommended for mixed repos) - GraphRAG with JSON persistence,
   AST/code metadata for code chunks, and LangExtract for docs/prose chunks
3. sqlite + AST + LangExtract - Same extractor behavior with the sqlite persistent + temporal graph store
4. AST only - GraphRAG with JSON persistence and AST/code metadata only
```

### Option mapping to config.yaml

The CLI wizard prompt text mirrors the current command implementation:

- `2) AST for code + LangExtract for docs (recommended for mixed repos)`
- `3) sqlite + AST for code + LangExtract for docs`
- `4) AST for code only`

### If Option 2 (AST + doc extraction, subagent, simple JSON persistence):

Add to config.yaml:

```yaml
graphrag:
  enabled: true
  store_type: "simple"
  use_code_metadata: true
extraction:
  mode: "subagent"
```

### If Option 3 (sqlite + AST + doc extraction, subagent):

The `sqlite` store is built on the Python stdlib `sqlite3` — no extra dependency
to install. It is persistent across restarts and adds temporal validity
(decision history, supersession) that the in-memory `simple` store lacks.

Add to config.yaml:

```yaml
graphrag:
  enabled: true
  store_type: "sqlite"
  use_code_metadata: true
extraction:
  mode: "subagent"
```

### If Option 4 (AST only):

```yaml
graphrag:
  enabled: true
  store_type: "simple"
  use_code_metadata: true
```

**Note:** Enabling GraphRAG increases indexing time. Re-index after enabling:
```bash
brainpalace reset --yes && brainpalace index ./your-docs
```

> **Extraction engine (`extraction.mode`).** Controls how doc-graph triplets AND
> session distillation are processed. `subagent` = free (Claude Code Haiku, no API
> cost); `provider` = server-side LLM (BILLABLE — also needs
> `EXTRACTION_PROVIDER_ENABLED=true`); `auto` = subagent + paid safety-net after
> `grace_hours`; `off` = code-AST graph only (default, cost-safe). The same rule
> applies to the BM25 `lemma` engine (`simplemma`) and the postgres backend
> (`asyncpg` + `sqlalchemy`). `brainpalace doctor` reports optional-extra status
> for enabled features.

### If Option 2 or 3: AskUserQuestion: GraphRAG Tuning (Optional)

After extraction mode selection, offer tuning:

```
Would you like to tune GraphRAG extraction settings?
(Default values work well for most projects)

Options:
1. Use defaults — traversal_depth=2, max_triplets=10 per chunk
2. Customize — adjust depth and triplet density
```

**If Option 2 (Customize):**

```bash
# Traversal depth: how many hops to follow from a matched entity (default: 2)
# Higher = richer context, slower queries (range: 1-5)
export GRAPH_TRAVERSAL_DEPTH=2

# Max triplets per chunk (default: 10)
# Higher = more relationships extracted, slower indexing
export GRAPH_MAX_TRIPLETS_PER_CHUNK=10
```

Config YAML equivalent:
```yaml
graphrag:
  traversal_depth: 2
  max_triplets_per_chunk: 10
```

## Step 8: Configure Caching

### Embedding Cache

The embedding cache reduces API costs by storing computed embeddings locally (two-tier: in-memory LRU + SQLite disk). Always beneficial for cloud providers; less relevant for Ollama.

### AskUserQuestion: Embedding Cache

```
Configure embedding cache settings?

The embedding cache avoids recomputing embeddings for unchanged content.
Healthy cache shows >80% hit rate after first full index.

Options:
1. Use defaults - 500 MB disk cache, 1000 in-memory entries
2. Customize - Set disk size and memory entries manually
3. Disable - No caching (not recommended for cloud providers)
```

**If Option 2 (Customize):** Ask for disk limit (MB) and memory entries, then add to config.yaml:

```yaml
cache:
  embedding_max_disk_mb: <user_value>     # e.g. 1000
  embedding_max_mem_entries: <user_value> # e.g. 2000
```

Or via environment variables:
```bash
export EMBEDDING_CACHE_MAX_DISK_MB=1000
export EMBEDDING_CACHE_MAX_MEM_ENTRIES=2000
```

**If Option 3 (Disable):**
```bash
export EMBEDDING_CACHE_MAX_DISK_MB=0
```

### Query Cache

The query cache stores identical query results for a TTL window. Graph and multi-mode queries are never cached.

### AskUserQuestion: Query Cache

```
Configure query result cache?

Caches repeated identical queries to reduce latency.
Note: graph and multi-mode queries are never cached.

Options:
1. Use defaults - 300s TTL, 256 max results
2. Customize - Set TTL and max size
3. Disable - TTL=0 (no caching)
```

**If Option 2 (Customize):** Add to config.yaml:

```yaml
cache:
  query_cache_ttl: <seconds>    # e.g. 600 for stable codebases
  query_cache_max_size: <count> # e.g. 512 for large query workloads
```

Or via environment variables:
```bash
export QUERY_CACHE_TTL=600
export QUERY_CACHE_MAX_SIZE=512
```

**If Option 3 (Disable):**
```bash
export QUERY_CACHE_TTL=0
```

## Step 9: Configure File Watcher (Auto-Reindex on Change)

### AskUserQuestion: File Watcher

```
Would you like to enable automatic re-indexing when files change?

Options:
1. Disabled (Default) — Index manually with `brainpalace index`
2. Enabled — Server watches indexed folders and re-indexes changed files
             Debounce: 30s by default (prevents re-index thrashing on rapid saves)
```

### If Option 2 (Enabled):

Ask for global debounce (default 30s, valid range 5–300s):

```
How many seconds should the watcher wait after a file change before re-indexing?
(Default: 30s — prevents re-indexing on every keystroke during active editing)
```

Set the global debounce via environment variable:

```bash
export BRAINPALACE_WATCH_DEBOUNCE_SECONDS=30
```

**Key facts about the file watcher:**

| Item | Detail |
|------|--------|
| Global debounce | `BRAINPALACE_WATCH_DEBOUNCE_SECONDS` (default 30s) |
| Per-folder watch | Set at index time, not in config.yaml |
| Enable per folder | `brainpalace folders add ./src --watch auto --debounce 10` |
| Disable per folder | `brainpalace folders add ./src --watch off` |
| View watch status | `brainpalace folders list` shows watch_mode per folder |
| Job source | Watcher-triggered jobs appear with `source="auto"` in queue |
| Deduplication | Same path is never double-indexed (dedupe_key prevents this) |

**Note:** `watch_mode` is a per-folder setting configured at index time. The
`BRAINPALACE_WATCH_DEBOUNCE_SECONDS` env var sets the global default debounce that
applies when no per-folder override is set.

```
Step 9 Complete: File Watcher
==============================

Global debounce: 30s
  BRAINPALACE_WATCH_DEBOUNCE_SECONDS=30

Per-folder watcher is configured at index time:
  brainpalace folders add ./src --watch auto              # use global debounce
  brainpalace folders add ./docs --watch auto --debounce 10  # 10s override

View current watch settings:
  brainpalace folders list

Restart server to apply:
  brainpalace stop && brainpalace start
```

---

## Step 10: Configure Reranking (Two-Stage Search Quality)

Reranking adds a second-pass scoring pass after the initial hybrid search, re-ranking
candidates with a cross-encoder model for higher precision results. It's off by default
because it requires additional model downloads.

### AskUserQuestion: Reranking

```
Would you like to enable two-stage reranking for higher search precision?

Reranking re-scores the top candidates with a cross-encoder model, improving
result quality at the cost of slightly higher query latency.

Options:
1. Disabled (Default) — single-stage hybrid BM25 + vector search
2. Enabled (sentence-transformers) — local cross-encoder, no API key needed
   Requires: pip install sentence-transformers (first run auto-downloads ~90 MB)
3. Enabled (Ollama) — uses Ollama for reranking, requires Ollama running
```

**If Option 2 (sentence-transformers):**

```bash
export ENABLE_RERANKING=true
export RERANKER_PROVIDER=sentence-transformers
export RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2  # default
```

Config YAML (`reranker` block):
```yaml
reranker:
  provider: "sentence-transformers"
  model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
```

**If Option 3 (Ollama):**

```bash
export ENABLE_RERANKING=true
export RERANKER_PROVIDER=ollama
```

Config YAML:
```yaml
reranker:
  provider: "ollama"
  base_url: "http://localhost:11434"
```

**Advanced tuning** (rarely needed):
```bash
# How many candidates Stage 1 retrieves for Stage 2 to rerank (default: top_k × 10)
export RERANKER_TOP_K_MULTIPLIER=10
# Hard cap on Stage 1 candidates (default: 100)
export RERANKER_MAX_CANDIDATES=100
```

---

## Step 11: Chunking & Search Tuning

Default values work well for most projects. Ask only if the user wants to tune
indexing quality or search behavior.

### AskUserQuestion: Tuning

```
Would you like to adjust chunking and search defaults?
(These affect indexing quality and search result count)

Options:
1. Use defaults — chunk_size=512, overlap=50, top_k=5, threshold=0.7
2. Customize — adjust for your content type
3. Skip
```

**If Option 2 (Customize):**

#### Chunk Size

```
What chunk size would you like?

Larger chunks = more context per result but less precise retrieval.
Smaller chunks = more precise but may cut mid-thought.

Recommended by content type:
- Source code:      256–512  (default: 512)
- Prose/docs:       512–1024
- Long-form books:  1024–2048

Enter chunk size (128–2048, default: 512):
```

```bash
export DEFAULT_CHUNK_SIZE=512
export DEFAULT_CHUNK_OVERLAP=50   # tokens of overlap between adjacent chunks
```

#### Search Top-K

```
How many results should queries return by default? (default: 5, max: 50)
```

```bash
export DEFAULT_TOP_K=5
```

#### Similarity Threshold

```
Minimum similarity score to include a result (0.0–1.0, default: 0.7)

Lower = more results but potentially less relevant.
Higher = fewer but more precise results.
```

```bash
export DEFAULT_SIMILARITY_THRESHOLD=0.7
```

Config YAML (no `chunking` block — these are env-var only settings):
```bash
# All chunking/query settings are env-var only (not in config.yaml)
export DEFAULT_CHUNK_SIZE=512
export DEFAULT_CHUNK_OVERLAP=50
export DEFAULT_TOP_K=5
export DEFAULT_SIMILARITY_THRESHOLD=0.7
```

---

## Step 12: Server & Deployment Configuration

### AskUserQuestion: Deployment Mode

```
How will BrainPalace be deployed?

Options:
1. Local (Default) — binds to 127.0.0.1 using an auto-discovered available port
   from 8000-8300
2. Network — binds to 0.0.0.0 or specific IP, accessible from other machines
3. Custom port — same as option 1 but allows overriding the suggested port
```

### Auto-discover available API port before prompting

Before asking for the final API port value, scan 8000-8300 and suggest the first
available port:

```bash
API_PORT=""
for port in $(seq 8000 8300); do
  if ! lsof -i :$port -sTCP:LISTEN >/dev/null 2>&1; then
    API_PORT=$port
    echo "Discovered available API port in 8000-8300 range: $port"
    break
  fi
done

if [ -z "$API_PORT" ]; then
  echo "ERROR: No available API ports in 8000-8300"
  exit 1
fi
```

Prompt with the discovered value as default/suggestion:

```text
API port [<discovered-port>]:
```

### Host and port mapping

**If Option 1 (Local):**

```bash
export API_HOST=127.0.0.1
export API_PORT=<DISCOVERED_PORT>
```

**If Option 2 (Network):**

```bash
# Bind address (default: 127.0.0.1 — localhost only)
# Use 0.0.0.0 to accept connections from any interface
export API_HOST=0.0.0.0

# Port uses discovered default from 8000-8300 unless user overrides
export API_PORT=<DISCOVERED_PORT_OR_OVERRIDE>
```

**If Option 3 (Custom port):**

```bash
export API_HOST=127.0.0.1
export API_PORT=<USER_SELECTED_PORT>
```

**Security note for network deployment:**
```
WARNING: Binding to 0.0.0.0 exposes BrainPalace to your local network.
BrainPalace has no built-in authentication. Use a reverse proxy (nginx, Caddy)
with authentication in front of it for network deployments.
```

### Multi-Instance Mode (Advanced)

If running multiple BrainPalace instances (one per project):

```bash
# "project" (default) — state stored in .brainpalace/ in current directory
# "shared" — state stored in BRAINPALACE_STATE_DIR (one shared index)
export BRAINPALACE_MODE=project

# Override state directory (overrides project-level .brainpalace/)
# export BRAINPALACE_STATE_DIR=/custom/path/to/state
```

### Debug Mode

```bash
# Enable verbose logging (default: false)
# export DEBUG=true
```

---

## BM25 Language Configuration

BM25 keyword search can be configured to use the correct stemmer/tokenizer for the project's primary language, improving retrieval quality for non-English content.

### AskUserQuestion: BM25 Language

After the chunking and search tuning step, ask:

```
What language is the majority of your indexed content written in?

BrainPalace's BM25 index uses language-aware stemming/lemmatization.
Default is English (en). Set this to match your documents.

Examples: en (English), de (German), fr (French), es (Spanish),
          ru (Russian), it (Italian), pt (Portuguese), nl (Dutch),
          hr (Croatian, requires lemma engine + brainpalace[lemma-hr])

Options:
1. English (en) — default
2. German (de)
3. French (fr)
4. Spanish (es)
5. Other — enter ISO 639-1 code
```

### BM25 Config Block

Add to `.brainpalace/config.yaml`:

```yaml
bm25:
  language: "en"               # ISO 639-1 project default (e.g. de, fr, es, ru, hr)
  engine: "stem"               # stem (Snowball/PyStemmer, ~27 languages) or lemma (simplemma)
  detect: false                # opt-in per-document language detection
  detect_min_confidence: 0.6   # minimum confidence to accept detected language (0–1)
```

Or set via `brainpalace init`:

```bash
brainpalace init --language de
brainpalace init --language hr --bm25-engine lemma
```

### BM25 Config Keys Reference

| Key | Default | Description |
|-----|---------|-------------|
| `bm25.language` | `en` | ISO 639-1 project default NL language for BM25 tokenization |
| `bm25.engine` | `stem` | Tokenization engine: `stem` (Snowball/PyStemmer) or `lemma` (simplemma) |
| `bm25.detect` | `false` | Enable per-document automatic language detection (opt-in) |
| `bm25.detect_min_confidence` | `0.6` | Minimum confidence threshold (0–1) for language detection to override the default |

### Notes

- **Supported languages**: ~27 Snowball/PyStemmer language codes (`en`, `de`, `fr`, `es`, `it`, `pt`, `nl`, `ru`, `sv`, `da`, `fi`, `no`, `hu`, `ro`, `tr`, and more) plus a custom Croatian stemmer (`hr`). Unknown codes fall back to English tokenization.
- **`engine: lemma`**: Requires the `simplemma` library (Croatian tier; lemmatizes via the Serbo-Croatian `hbs` data). Install with `pip install 'brainpalace[lemma-hr]'`. For all other languages, `engine: stem` is correct.
- **Reindex on change**: Changing `bm25.language` or `bm25.engine` changes tokenization; the BM25 index auto-rebuilds from the stored corpus on the next server start (analyzer fingerprint is persisted). To re-detect per-document languages, re-run indexing.
- **PostgreSQL BM25**: When `storage.backend: "postgres"` is used, BM25 is handled by PostgreSQL's native full-text search (`tsvector`). Language is configured via `storage.postgres.language` (e.g. `"english"`) — a separate setting from `bm25.language`.

---

## Advanced Configuration Reference

Settings not covered by the wizard (rarely need changing):

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CHROMA_PERSIST_DIR` | `./chroma_db` | ChromaDB storage directory |
| `BM25_INDEX_PATH` | `./bm25_index` | BM25 keyword index directory |
| `COLLECTION_NAME` | `brainpalace_collection` | ChromaDB collection name |
| `EMBEDDING_DIMENSIONS` | `3072` | Vector dimensions (must match model) |
| `EMBEDDING_BATCH_SIZE` | `100` | API batch size for embedding calls |
| `MAX_CHUNK_SIZE` | `2048` | Hard cap on chunk size |
| `MIN_CHUNK_SIZE` | `128` | Minimum chunk size |
| `MAX_TOP_K` | `50` | Maximum results per query |
| `BRAINPALACE_MAX_QUEUE` | `100` | Max pending jobs in queue |
| `BRAINPALACE_JOB_TIMEOUT` | `7200` | Job timeout in seconds (2 hours) |
| `BRAINPALACE_MAX_RETRIES` | `3` | Job retry attempts on failure |
| `BRAINPALACE_CHECKPOINT_INTERVAL` | `50` | Progress save interval (files) |
| `EMBEDDING_CACHE_PERSIST_STATS` | `false` | Persist cache hit/miss stats across restarts |
| `BRAINPALACE_STRICT_MODE` | `false` | Fail on critical validation errors |
| `GRAPH_EXTRACTION_MODEL` | `claude-haiku-4-5` | LLM model for legacy LLM entity extraction |
| `GRAPH_RRF_K` | `60` | Reciprocal Rank Fusion constant for graph queries |

All settings can be placed in a `.env` file in the server directory or set as environment variables.

---

## CLI Subcommands Reference

The `brainpalace config` group has these subcommands:

| Subcommand | Description |
|------------|-------------|
| `brainpalace config show` | Display active provider configuration (embedding, summarization, reranker) |
| `brainpalace config path` | Show the path to the active config file |
| `brainpalace config wizard` | Create/update config interactively |
| `brainpalace config validate` | Validate config against the schema |
| `brainpalace config migrate` | Upgrade config.yaml to the current schema version |
| `brainpalace config diff` | Preview what `migrate` would change |
| `brainpalace config unset <dotpath>` | Remove a project override so the key inherits again |

`show`, `path`, and `unset` support `--json` for machine-readable output.

## Related Commands

- `/brainpalace:brainpalace-embeddings` - Configure embedding provider only
- `/brainpalace:brainpalace-index` - Index documents with current exclude settings
- `/brainpalace:brainpalace-init` - Initialize project (creates .brainpalace/ directory)

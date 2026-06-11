---
name: brainpalace-setup
description: Complete guided setup for BrainPalace (install, config, init, verify)
parameters: []
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-06-11
---

# Complete BrainPalace Setup

## Purpose

Runs a complete guided setup flow for BrainPalace, taking the user from zero to a fully working installation. This command orchestrates installation, configuration, initialization, and verification steps.

## Usage

```
/brainpalace-setup
```

## Execution

Run each step in sequence, proceeding only if the previous step succeeds.

### Step 0: Bootstrap Permissions

Before running any shell commands, ensure `.claude/settings.json` exists with the required permissions for the setup wizard. Use the Write tool (not Bash) to create this file — the Write tool is always available without a permission gate.

Check if the file already exists:

```bash
ls .claude/settings.json 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing or if it does not contain `"Bash(brainpalace:*)"`, write the following content to `.claude/settings.json` using the Write tool:

```json
{
  "_comment": "BrainPalace setup permissions — written by /brainpalace-setup. Safe to commit.",
  "permissions": {
    "allow": [
      "Bash(brainpalace:*)",
      "Bash(lsof:*)",
      "Bash(ollama:*)",
      "Bash(docker:*)",
      "Bash(mkdir:*)",
      "Bash(cat:*)",
      "Bash(jq:*)",
      "Bash(mv:*)",
      "Bash(du:*)",
      "Bash(ps:*)",
      "Bash(pgrep:*)",
      "Bash(pip:*)",
      "Bash(pipx:*)",
      "Bash(uv:*)",
      "Bash(python:*)",
      "Bash(python3:*)",
      "Bash(rg:*)",
      "Bash(wc:*)",
      "Bash(curl:*)",
      "Bash(ls:*)",
      "Bash(find:*)",
      "Bash(chmod:*)",
      "Bash(grep:*)",
      "Bash(bash:*)"
    ],
    "deny": []
  }
}
```

After writing the file, tell the user:
"Wrote `.claude/settings.json` with BrainPalace setup permissions. These allow the wizard to run without permission prompts. The file is safe to commit — it grants access only to standard development tools."

**IMPORTANT:** If `.claude/settings.json` already exists with custom content, MERGE: add any missing `Bash(...)` entries from the list above into the existing `allow` array rather than replacing the file.

### Step 1: Check Installation Status

```bash
brainpalace --version 2>/dev/null || echo "NOT_INSTALLED"
```

If not installed, run `/brainpalace-install` first.

**Environment pre-flight:** After confirming installation, run the detection script to collect environment state for all subsequent steps:

```bash
SCRIPT=$(find ~/.claude/plugins/brainpalace/scripts ~/.claude/skills/brainpalace/scripts brainpalace-plugin/scripts -name "ab-setup-check.sh" 2>/dev/null | head -1)
SETUP_STATE=$( [ -n "$SCRIPT" ] && bash "$SCRIPT" || echo "{}" )
echo "$SETUP_STATE"
```

Store `SETUP_STATE` in memory for use in Steps 2-11. This avoids re-running individual detection commands later.

### Step 2: Wizard — Embedding Provider

Use AskUserQuestion to ask which embedding provider to use:

```
Which embedding provider would you like to use for BrainPalace?

Options:
1. Ollama (FREE, local) - nomic-embed-text, runs on your machine, no API key needed
2. OpenAI - text-embedding-3-large, best quality cloud embeddings, requires OPENAI_API_KEY
3. Cohere - embed-multilingual-v3.0, multi-language support, requires COHERE_API_KEY
4. Google Gemini - text-embedding-004, Google's cloud embeddings, requires GOOGLE_API_KEY
5. Custom - specify your own provider, model, and base_url
```

Record the selection as `embedding.provider` and `embedding.model`. If a cloud provider is selected, ask for the API key or `api_key_env` reference:

```
Please provide your API key for the selected provider.

Options:
1. Enter API key directly (will be stored in config.yaml)
2. Use environment variable reference (recommended) - e.g., OPENAI_API_KEY
```

For Ollama, also record `embedding.base_url: "http://localhost:11434/v1"`.

### Step 3: Wizard — Summarization Provider

> **What this provider is for.** It makes short LLM summaries of your **CODE**
> during indexing (improves search quality) — always needed, independent of any
> plugin. Your **chat/session** summaries are a separate job, handled **FREE** by
> the Claude Code plugin. Without the plugin, chat summarization is **OFF by
> default** — the server-side provider distiller is doubly opt-in (`mode:
> provider`/`auto` **and** `SESSION_DISTILL_ENABLED=true`). So in practice this
> provider is for **code only** unless you explicitly opt in.

Use AskUserQuestion to ask which summarization provider to use. **Default** to
the provider chosen for embedding in Step 2 when it can also summarize
(`openai` → OpenAI, `ollama` → Ollama); otherwise default to whichever
summarization API key is already set in the environment (`OPENAI_API_KEY` →
OpenAI, `ANTHROPIC_API_KEY` → Anthropic, `GOOGLE_API_KEY` → Gemini), falling back
to Anthropic. (Mirrors the CLI `config wizard` behavior — keep them aligned.)

```
Which summarization provider would you like to use for BrainPalace?

Options:
1. Ollama (FREE, local) - llama3.2, runs on your machine, no API key needed
2. Ollama + Mistral (FREE, local) - mistral-small3.2, better summarization quality, no API key needed
3. Anthropic - claude-haiku-4-5-20251001, fast and cost-effective, requires ANTHROPIC_API_KEY
4. OpenAI - gpt-4o-mini, OpenAI summarization, requires OPENAI_API_KEY
5. Google Gemini - gemini-3.1-flash-lite, Google's model, requires GOOGLE_API_KEY
6. Grok (xAI) - grok-3-mini-fast, xAI's fast model, requires XAI_API_KEY
```

Record the selection as `summarization.provider` and `summarization.model`. If a cloud provider is selected, ask for the API key or `api_key_env` reference (same as embedding step). For Ollama options, record `summarization.base_url: "http://localhost:11434/v1"`.

### Step 4: Wizard — Storage Backend

Use AskUserQuestion to ask which storage backend to use:

```
Which storage backend would you like to use for BrainPalace?

Options:
1. ChromaDB (Default) - Local-first, zero ops, best for small to medium projects, no infrastructure needed
2. PostgreSQL + pgvector - Best for larger datasets, team environments, requires Docker or existing database
```

Record the selection as `storage.backend` (value: `"chroma"` or `"postgres"`).

If PostgreSQL is selected, note that the PostgreSQL setup step (Step 10a) will handle Docker port auto-discovery and container startup. The config will be updated with the discovered port automatically.

If PostgreSQL is selected, add this informational note to wizard output:

> **BM25 + PostgreSQL:** PostgreSQL replaces the disk-based BM25 index with
> built-in full-text search (`tsvector` + `websearch_to_tsquery`). The
> `--mode bm25` command still works identically from your perspective.
> Language is configurable via `storage.postgres.language` (default: `english`).

### Step 5: Wizard — GraphRAG

Check the storage backend selected in Step 4:

**If storage backend is `postgres`:**
Use AskUserQuestion to inform the user (not a choice — informational only):

```
GraphRAG requires ChromaDB backend and is not available with PostgreSQL.

GraphRAG will be disabled (graphrag.enabled: false).

If you want GraphRAG in the future, switch to ChromaDB storage backend.
```

Record `graphrag.enabled: false` and `graphrag.store_type: "simple"`.
Skip to Step 6.

**If storage backend is `chroma`:**
Use AskUserQuestion to ask whether to enable GraphRAG:

```
Would you like to enable GraphRAG (graph-based retrieval)?

GraphRAG extracts entity relationships from documents and code, enabling graph-aware
and multi-mode queries (--mode graph, --mode multi).

Note: To use graph mode, index documents with:
  brainpalace index ./src --include-code

Options:
1. Yes - SQLite (Default, Recommended) - Persistent, incrementally-writable, temporal-validity tracking
2. Yes - SimplePropertyGraphStore - In-memory JSON graph, no temporal tracking
3. No - Use standard vector + BM25 hybrid search only
```

> **Default store is `sqlite`.** `brainpalace init` enables GraphRAG with
> `graphrag.store_type: sqlite` — persistent, incrementally-writable, and
> temporal-validity aware. The legacy `simple` store is in-memory JSON with no
> temporal tracking.

If enabled, record:
- `graphrag.enabled: true`
- `graphrag.store_type: "sqlite"` (default) or `"simple"`
- `graphrag.use_code_metadata: true`

If GraphRAG is disabled, record `graphrag.enabled: false`.

### Step 6: Wizard — Default Query Mode

Use AskUserQuestion to ask which default query mode to use. Constrain options based on GraphRAG selection from Step 5:

**If GraphRAG is disabled (Step 5 selected No):**

```
Which default query mode would you like to use?

Options:
1. hybrid (Recommended) - Combines vector similarity + BM25 keyword matching for best results
2. semantic - Pure vector similarity search
3. bm25 - Keyword-only search (fast, no embedding needed)
```

**If GraphRAG is enabled (Step 5 selected Yes):**

```
Which default query mode would you like to use?

Options:
1. hybrid (Recommended) - Combines vector similarity + BM25 keyword matching
2. semantic - Pure vector similarity search
3. bm25 - Keyword-only search
4. graph - Entity relationship traversal (requires GraphRAG)
5. multi - Fuses vector + BM25 + graph with RRF (requires GraphRAG)
```

Record the selected mode. This will be written as a YAML comment in config.yaml (the server does not yet support a global `query.default_mode` setting — use `--mode` flag per request to override).

Note in wizard output: "Use --mode flag on queries to override, e.g.: `brainpalace query 'text' --mode hybrid`"

After the mode selection, add this informational note to wizard output:

> **Caching (auto-enabled):** Both embedding and query caches are automatically
> active — no configuration needed.
> - **Embedding cache**: Reindexing unchanged files costs zero API calls.
> - **Query cache**: Repeat queries return instantly (TTL: 5 minutes by default).
> - **Note**: `graph` and `multi` modes bypass the query cache (always fresh).

### Step 7: Wizard — Write config.yaml

Write the provider config to the **global** XDG location
(`~/.config/brainpalace/config.yaml`) that every project inherits. There is no
project-scoped or legacy `~/.brainpalace/` fallback — a project gets this config
when you run `brainpalace init` in Step 10.

```bash
# Global-first: provider config is written ONCE to the XDG global config that
# every `brainpalace init` (and the CLI) inherits. No project/legacy fallback.
CONFIG_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/brainpalace/config.yaml"
echo "Global config path: $CONFIG_PATH"
if [ -f "$CONFIG_PATH" ]; then
  echo "Existing global config found — will update it."
fi
```

If an existing config is found, use AskUserQuestion:

```
An existing GLOBAL config.yaml was found at: ~/.config/brainpalace/config.yaml

Options:
1. Update existing config - Merge wizard settings into current config
2. Create fresh config - Replace existing config with wizard settings (backup will be created)
3. Skip - Keep existing config unchanged and proceed
```

If creating or updating, write a comprehensive config.yaml using Python for safe YAML serialization:

```bash
mkdir -p "$(dirname "$CONFIG_PATH")"
python3 -c "
import yaml, sys

config = {
    'embedding': {
        'provider': '<SELECTED_EMBEDDING_PROVIDER>',
        'model': '<SELECTED_EMBEDDING_MODEL>',
    },
    'summarization': {
        'provider': '<SELECTED_SUMMARIZATION_PROVIDER>',
        'model': '<SELECTED_SUMMARIZATION_MODEL>',
    },
    'storage': {
        'backend': '<SELECTED_STORAGE_BACKEND>',
    },
    'graphrag': {
        'enabled': <GRAPHRAG_ENABLED>,
        'store_type': '<GRAPHRAG_STORE_TYPE>',
        'use_code_metadata': True,
    },
}

# Add base_url for Ollama
if config['embedding']['provider'] == 'ollama':
    config['embedding']['base_url'] = 'http://localhost:11434/v1'
if config['summarization']['provider'] == 'ollama':
    config['summarization']['base_url'] = 'http://localhost:11434/v1'

# Add API key or api_key_env for cloud providers
# (Fill in from wizard selections)

print(yaml.dump(config, default_flow_style=False, sort_keys=False))
" > "$CONFIG_PATH"

# Append query mode as a comment
echo "" >> "$CONFIG_PATH"
echo "# Query mode (informational — set per-request with --mode flag)" >> "$CONFIG_PATH"
echo "# query:" >> "$CONFIG_PATH"
echo "#   default_mode: \"<SELECTED_QUERY_MODE>\"  # vector | bm25 | hybrid | graph | multi" >> "$CONFIG_PATH"

chmod 600 "$CONFIG_PATH"
echo "Global config written to: $CONFIG_PATH"
echo "Validating..."
brainpalace config validate || echo "WARN: config validate reported issues — review above."
echo "SECURITY WARNING: Never commit this file to git — it may contain API keys"
```

### Step 8: Wizard — Verify Connectivity

Run `brainpalace verify` to validate that the selected providers are reachable:

```bash
brainpalace verify
```

If verify fails, show troubleshooting guidance:

```
Provider verification failed. Common issues:

For Ollama:
  - Ensure Ollama is running: ollama serve
  - Ensure models are pulled: ollama pull nomic-embed-text && ollama pull llama3.2

For OpenAI:
  - Check OPENAI_API_KEY is set or api_key is correct in config.yaml
  - Test: curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"

For Anthropic:
  - Check ANTHROPIC_API_KEY is set or api_key is correct in config.yaml

Would you like to re-run the wizard to correct your provider settings? (Yes / No)
```

If the user chooses Yes, restart from Step 2. If No, continue to the next step.

### Step 9: Wire an MCP Client (optional)

For users who ALSO use a non-Claude MCP client (Cursor, VS Code, Cline,
Continue, Kilo, Zed). If they only use this Claude Code plugin, skip this step.

Use AskUserQuestion to ask which MCP client to wire:

```
Which MCP client would you like to wire BrainPalace into?

Options:
1. None — CLI / Claude Code plugin only (Default)
2. VS Code → .vscode/mcp.json
3. Cursor → .cursor/mcp.json
4. Cline → .cline/mcp.json
5. Continue → .continue/mcp.yaml
6. Kilo Code → .kilo/kilo.jsonc
7. Zed → .zed/settings.json
```

If none, skip to Step 10.

If a client is selected, use AskUserQuestion to ask the scope:

```
Where should the MCP config file be written?

Options:
1. User scope (HOME — recommended, applies everywhere) (Default)
2. Project scope (the project you set up in Step 10)
```

Resolve the absolute binary path:

```bash
AB_BIN="$(command -v brainpalace)"
echo "Using brainpalace at: $AB_BIN"
```

Then use the Write tool to create the client's config file under `$HOME` (user
scope) — or under the project root if the user chose project scope AND a project
path is known. Use the absolute `$AB_BIN` path.

**Per-client config templates** (replace `<AB_BIN>` with the resolved path):

**VS Code** → `$HOME/.vscode/mcp.json`
```json
{
  "servers": {
    "brainpalace": {
      "type": "stdio",
      "command": "<AB_BIN>",
      "args": ["mcp", "--ensure-server"]
    }
  }
}
```

**Cursor** → `$HOME/.cursor/mcp.json`
```json
{
  "mcpServers": {
    "brainpalace": {
      "command": "<AB_BIN>",
      "args": ["mcp", "--ensure-server"]
    }
  }
}
```

**Cline** → `$HOME/.cline/mcp.json`
```json
{
  "mcpServers": {
    "brainpalace": {
      "command": "<AB_BIN>",
      "args": ["mcp", "--ensure-server"],
      "disabled": false
    }
  }
}
```

**Continue** → `$HOME/.continue/mcp.yaml`
```yaml
mcpServers:
  - name: brainpalace
    command: <AB_BIN>
    args: ["mcp", "--ensure-server"]
```

**Kilo Code** → `$HOME/.kilo/kilo.jsonc`
```json
{
  "mcp": {
    "brainpalace": {
      "type": "local",
      "command": ["<AB_BIN>", "mcp", "--ensure-server"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

**Zed** → `$HOME/.zed/settings.json`
```json
{
  "context_servers": {
    "brainpalace": {
      "command": {
        "path": "<AB_BIN>",
        "args": ["mcp", "--ensure-server"]
      }
    }
  }
}
```

If the target file already exists, back it up first (`<path>.bak.<timestamp>`)
before writing. Tell the user the absolute path was baked in to avoid
PATH-inheritance failures.

### Step 10: Set Up a Project (optional, last)

This is the LAST step and is optional. The global provider config from Step 7 is
already in place; a project just needs `brainpalace init` to inherit it.

Use AskUserQuestion:

```
Initialise and index a project now?

Options:
1. Yes — set up the current project (Default)
2. No — I'll run `brainpalace init` in a project later
```

If No, print the following hint and skip to summary:

```
BrainPalace is installed and configured globally. To set up a project later:

    cd /path/to/your/project
    brainpalace init

The provider is configured globally — new projects inherit it.
```

> **Note:** If the storage backend chosen in Step 4 is `postgres`, run the
> PostgreSQL sub-flow below (Step 10a) BEFORE `brainpalace init` so the server
> can connect on first start.

> **Same question set as the wizard.** `brainpalace init` (sparse PROJECT config)
> asks the **same project-config-backed questions** as the `config wizard` /
> `install` GLOBAL flow above: embedding, summarizer, **reranker**,
> **embed-sessions** (`session_indexing.enabled` — billable opt-in, default OFF),
> **session-archive** (`session_indexing.archive.enabled` — free local backup of
> full raw transcripts incl. secrets, default ON), **git-history**, and **GraphRAG
> document extraction** (`graphrag.doc_extractor` = `langextract` | `none`). `init`
> re-asks the per-project-overridable **reranker** (`reranker.enabled`)
> behind an *"inherited from global — change for this project? [y/N]"* gate,
> writing a sparse override only when changed; embedding/summarizer are not
> re-asked via that gate (they resolve via env-detection / global inheritance).

> **Opt-in optional-dep rule.** Enabling a feature whose "yes" needs an optional
> server extra triggers a download — **auto-installed on yes** (auto-detecting
> pipx → uv → pip), or the **exact install command is printed** if no manager is
> detected. Declining writes the disabling value (e.g. `graphrag.doc_extractor:
> none`) so the server's "not installed" warning never fires; optional deps are
> never auto-installed just because a feature is default-ON in code. Extras:
> GraphRAG doc-extraction → `langextract`; BM25 `lemma` engine → `simplemma`;
> postgres backend → `asyncpg` + `sqlalchemy`. `brainpalace doctor` reports
> optional-extra status for enabled features.

> **Session summarization:** `brainpalace init` enables it by default and writes
> `mode: subagent` — sessions are summarized **only inside Claude Code**. Since
> you're installing the plugin here, it summarizes your sessions **for free on
> your Claude Code subscription** (Haiku, after your first turn — no separate API
> bill; it draws on your subscription's usage limits); the plugin owns its own
> hooks. The server never summarizes on its own, so there is **no surprise API
> bill**. Summaries run **after your first prompt** in batches of up to **8 sessions**
> (≤1 MB) with a **5-minute (300 s) cool-down** between batches — never on session start.
> Want server-side summarization anyway? Opt in with `mode: provider`
> (your configured AI — prefer a local Ollama summarizer for free + private) or
> `mode: auto` (defer to the plugin, server fallback with a 24h safety net). Opt
> out entirely with `brainpalace init --no-extract`.
> See docs/SESSION_INDEXING.md.

> **Git-history indexing (opt-in, default OFF):** `brainpalace init` can index
> this repo's git commit history (commit message + changed-file list) into
> searchable chunks. It is **off by default** because commit messages and diffs
> can contain secrets, so it is a deliberate opt-in. Interactive `init` asks a
> yes/no question (default **no**); pass `--git-history` / `--no-git-history` to
> decide non-interactively. When enabled, `git_indexing.enabled: true` is written
> to `.brainpalace/config.yaml`. Nothing is copied — chunks reference the commit
> sha.

If Yes, run:

```bash
brainpalace init
```

This inherits the global config and by default starts server + indexes after a
confirmation.

### Step 10a: PostgreSQL (Only When Backend Is Postgres)

PostgreSQL setup is only required if the storage backend selected in Step 4 is
`postgres` AND the user chose to set up a project in Step 10. Run this before
`brainpalace init`.

Check backend selection (env override takes priority):

```bash
echo "Backend override: ${BRAINPALACE_STORAGE_BACKEND:-unset}"
rg -n "backend:" "${XDG_CONFIG_HOME:-$HOME/.config}/brainpalace/config.yaml" .brainpalace/config.yaml 2>/dev/null
```

If the backend is `postgres`, confirm Docker and Docker Compose are available:

```bash
docker --version
docker compose version
```

If Docker is not available, pause and explain the user must install Docker or point `storage.postgres` to an existing PostgreSQL instance.

#### a: Check for existing brainpalace-postgres container

```bash
docker ps --filter name=brainpalace-postgres --format '{{.Ports}}' 2>/dev/null
```

If already running, extract the mapped port and skip to step e.

#### b: Find available port

```bash
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
  exit 1
fi
```

#### c: Start Docker Compose with discovered port

```bash
POSTGRES_PORT=$POSTGRES_PORT docker compose -f <plugin_path>/templates/docker-compose.postgres.yml up -d
```

#### d: Update config.yaml with discovered port

Write or update `storage.postgres.port` in the active config.yaml to use the discovered port. This ensures the server connects to the correct port automatically.

#### e: Verify PostgreSQL is ready

```bash
docker exec brainpalace-postgres pg_isready -U brainpalace -d brainpalace
```

### Step 11: Verify (only if a project was set up)

If a project was initialised in Step 10:

```bash
brainpalace status
```

Confirm the server is healthy. If init was declined, skip — there is no
project server to check yet.

## Output

Display progress through each step with clear status indicators:

```
BrainPalace Setup
=================

[0]    Permissions ..... .claude/settings.json [WRITTEN]
[1]    Install ......... OK (brainpalace <version>)
[2-6]  Provider wizard . CONFIGURED
[7]    Global config ... ~/.config/brainpalace/config.yaml [WRITTEN, chmod 600]
[8]    Connectivity .... OK
[9]    MCP client ...... <client or "skipped">
[10]   Project ......... <initialised path or "skipped — run `brainpalace init` later">
[11]   Verify .......... <OK or "skipped — no project initialised">

Setup complete.

The provider is configured globally — every `brainpalace init` inherits it.
```

## Error Handling

### Installation Failed

```
[1/?] Checking installation... FAILED

BrainPalace is not installed.

Running installation...
[Invoke /brainpalace-install]
```

### Provider Not Configured

```
[2-6] Embedding provider... INCOMPLETE

No embedding provider selected.

Re-running wizard from Step 2...
```

### Init Failed

```
[10]  Initializing project... FAILED

Error: Permission denied creating .brainpalace/

Solutions:
1. Check directory permissions
2. Ensure you have write access to current directory
3. Try: mkdir -p .brainpalace
```

### Server Start Failed

```
[10/start]  Starting server... FAILED

Error: Port already in use

Solutions:
1. Check for running instance: brainpalace list
2. Stop existing server: brainpalace stop
3. Clean state: rm -f .brainpalace/runtime.json
4. Retry: brainpalace start
```

### Verification Failed

```
[11]  Verifying setup... FAILED

Server started but health check failed.

Diagnostics:
1. Check logs: Check server output
2. Verify API key: Test provider connection
3. Restart: brainpalace stop && brainpalace start
```

## Resume Capability

If setup is interrupted, running `/brainpalace-setup` again will:
1. Skip already-completed steps
2. Resume from the failed step
3. Complete remaining steps

The setup is idempotent and safe to run multiple times.

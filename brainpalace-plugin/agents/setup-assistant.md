---
name: setup-assistant
description: Proactively assists with BrainPalace installation and configuration
triggers:
  - pattern: "install.*agent.?brain|setup.*brain|configure.*brain"
    type: message_pattern
  - pattern: "how do I.*search|need to.*index|want to.*query"
    type: keyword
  - pattern: "brainpalace.*not found|command not found.*agent"
    type: error_pattern
  - pattern: "OPENAI_API_KEY.*not set|missing.*api.*key"
    type: error_pattern
  - pattern: "connection refused.*postgres|could not connect to server|postgres.*connection refused"
    type: error_pattern
  - pattern: "pgvector|extension \"vector\" does not exist|could not open extension control file"
    type: error_pattern
  - pattern: "QueuePool.*limit|pool.*exhausted|too many connections"
    type: error_pattern
  - pattern: "embedding dimension mismatch|dimension mismatch"
    type: error_pattern
skills:
  - configuring-brainpalace
allowed_tools:
  - Read
  - Glob
  - "Bash(~/.claude/plugins/brainpalace/scripts/*)"
  - "Bash(.claude/plugins/brainpalace/scripts/*)"
  - "Write(~/.brainpalace/**)"
  - "Edit(~/.brainpalace/**)"
  - "Write(~/.config/brainpalace/**)"
  - "Edit(~/.config/brainpalace/**)"
  - "Write(.claude/brainpalace/**)"
  - "Edit(.claude/brainpalace/**)"
last_validated: 2026-03-16
---

# Setup Assistant Agent

Proactively helps users install, configure, and troubleshoot BrainPalace.

## When to Activate

This agent activates when detecting patterns suggesting the user needs setup assistance:

### Installation Triggers

- "install BrainPalace"
- "setup BrainPalace"
- "how do I install brainpalace"
- "need to set up document search"

### Configuration Triggers

- "configure BrainPalace"
- "set up API keys"
- "OPENAI_API_KEY not set"
- "missing api key"

### Feature Discovery Triggers

- "how do I search my docs"
- "need to index documents"
- "want to query my codebase"
- "looking for document search"

### Error Triggers

- "brainpalace: command not found"
- "ModuleNotFoundError: brainpalace"
- "server not running"
- "connection refused"

## Assistance Flow

When triggered, follow this diagnostic and resolution flow:

### 1. Check Installation Status

```bash
brainpalace --version 2>/dev/null || echo "NOT_INSTALLED"
```

**If not installed:**
- Explain what BrainPalace does
- Guide through installation with `/brainpalace-install`

### 2. Check API Keys

```bash
echo "${OPENAI_API_KEY:+SET}"
```

**If not set:**
- Explain why the key is needed
- Guide through configuration with `/brainpalace-config`

### 3. Check Project Initialization

```bash
ls .brainpalace/config.json 2>/dev/null
```

**If not initialized:**
- Explain project isolation
- Guide through initialization with `/brainpalace-init`

### 4. Check Server Status

```bash
brainpalace status 2>/dev/null
```

**If not running:**
- Offer to start the server
- Guide with `brainpalace start`

### 5. Verify Full Setup

Run `/brainpalace-verify` to confirm everything is working.

## Example Interactions

### Example 1: New User Wants Document Search

**User:** "I want to search my project documentation"

**Assistant Response:**
```
I can help you set up BrainPalace for document search. Let me check if it's installed...

BrainPalace is not currently installed. It provides:
- Semantic search: Find documents by meaning, not just keywords
- Hybrid search: Combines keyword and semantic matching
- Code search: AST-aware indexing for source code

Would you like me to walk you through the setup? I can run /brainpalace-setup
to guide you through installation, configuration, and initialization.

Quick setup takes about 2 minutes:
1. Install packages (pip install)
2. Configure OpenAI API key
3. Initialize for this project
4. Index your documents

Ready to begin?
```

### Example 2: Missing API Key Error

**User:** "I'm getting an error about OPENAI_API_KEY not set"

**Assistant Response:**
```
The OpenAI API key is required for BrainPalace's semantic search features.

Let me help you configure it:

1. Get your API key from: https://platform.openai.com/account/api-keys

2. Set it in your environment:
   export OPENAI_API_KEY="sk-proj-your-key-here"

3. For permanent setup, add to your shell profile:
   echo 'export OPENAI_API_KEY="your-key"' >> ~/.bashrc
   source ~/.bashrc

Security reminder: Never commit API keys to version control!

After setting the key, run /brainpalace-verify to confirm the configuration.
```

### Example 3: Command Not Found

**User:** "brainpalace: command not found"

**Assistant Response:**
```
BrainPalace doesn't appear to be installed yet. Let me help you set it up.

Quick install:
  pip install brainpalace-rag brainpalace-cli

If you're using a virtual environment, make sure it's activated:
  source .venv/bin/activate

After installation, verify with:
  brainpalace --version

Would you like me to run /brainpalace-install for a guided installation?
```

### Example 4: Server Connection Issues

**User:** "I can't connect to the brainpalace server"

**Assistant Response:**
```
Let me check the server status...

The BrainPalace server is not running.

To start it:
  brainpalace start

If that fails, try:
1. Check for stale state: rm -f .brainpalace/runtime.json
2. Start again: brainpalace start
3. Verify: brainpalace status

Common issues:
- Port conflict: Another service using the port
- Missing init: Run brainpalace init first
- API key issues: Verify OPENAI_API_KEY is set

Run /brainpalace-verify for a complete diagnostic.
```

## Proactive Suggestions

When the agent detects relevant context, offer helpful suggestions:

### User Opens New Project

"I notice this project doesn't have BrainPalace initialized. Would you like to set it up for document search?"

### User Has Markdown/Code Files

"This project has documentation that could be indexed for search. Run /brainpalace-setup to enable semantic search."

### User Asks About Finding Code

"For code search, BrainPalace offers AST-aware indexing that understands code structure. Would you like to set it up?"

## Error Recovery

When errors occur, provide clear recovery paths:

### Installation Errors

1. Check Python version
2. Try virtual environment
3. Use `pip install --user` flag
4. Check pip is configured correctly

### Configuration Errors

1. Verify key format
2. Test API connectivity
3. Check for typos in key
4. Regenerate key if needed

### Server Errors

1. Check port availability
2. Remove stale runtime files
3. Verify initialization
4. Check system resources

### PostgreSQL Backend Errors

**Connection refused / could not connect:**
1. Ensure PostgreSQL is running (Docker Compose or managed instance)
2. If using Docker: `docker compose -f brainpalace-plugin/templates/docker-compose.postgres.yml up -d`
3. Verify readiness: `docker compose -f brainpalace-plugin/templates/docker-compose.postgres.yml exec -T postgres pg_isready -U brainpalace`
4. Confirm `storage.postgres.host` and `storage.postgres.port` match the running instance

**pgvector extension missing:**
1. Use the pgvector image: `pgvector/pgvector:pg16`
2. For managed Postgres, run: `CREATE EXTENSION IF NOT EXISTS vector;`
3. Restart BrainPalace after installing the extension

**Pool exhaustion / too many connections:**
1. Increase `pool_size` and `pool_max_overflow` in `storage.postgres`
2. Restart the server to apply pool changes

**Embedding dimension mismatch:**
1. If you changed embedding models, run: `brainpalace reset --yes`
2. Re-index documents after reset

### Search Errors

1. Verify documents indexed
2. Check server health
3. Validate query syntax
4. Review index status

---

## Multi-Runtime Installation (v9.0+)

When users want to install BrainPalace for their AI coding assistant, guide them through multi-runtime installation:

```bash
# Install for Claude Code
brainpalace install-agent --agent claude

# Install for OpenCode
brainpalace install-agent --agent opencode

# Install for Gemini
brainpalace install-agent --agent gemini

# Install for Codex (skill directories + AGENTS.md)
brainpalace install-agent --agent codex

# Install for generic skill-based runtime
brainpalace install-agent --agent skill-runtime --dir /path/to/skills

# Preview what will be installed
brainpalace install-agent --agent claude --dry-run

# Global (user-level) installation
brainpalace install-agent --agent claude --scope global
```

### Supported Runtimes

| Runtime | Install Dir (project) | Format |
|---------|----------------------|--------|
| `claude` | `.claude/plugins/brainpalace` | Claude plugin |
| `opencode` | `.opencode/plugins/brainpalace` | OpenCode plugin |
| `gemini` | `.gemini/plugins/brainpalace` | Gemini plugin |
| `codex` | `.codex/skills/brainpalace` | Skill dirs + AGENTS.md |
| `skill-runtime` | (requires `--dir`) | Generic skill dirs |

---

## Provider Configuration (All 7 Providers)

Guide users through configuring all supported providers:

### Embedding Providers (3)

| Provider | Env Var | Models |
|----------|---------|--------|
| OpenAI | `OPENAI_API_KEY` | text-embedding-3-large, text-embedding-3-small |
| Cohere | `COHERE_API_KEY` | embed-english-v3.0, embed-multilingual-v3.0 |
| Ollama | (none - local) | nomic-embed-text, mxbai-embed-large |

### Summarization Providers (5)

| Provider | Env Var | Models |
|----------|---------|--------|
| Anthropic | `ANTHROPIC_API_KEY` | claude-haiku-4-5-20251001 |
| OpenAI | `OPENAI_API_KEY` | gpt-5, gpt-5-mini |
| Gemini | `GOOGLE_API_KEY` | gemini-3-flash, gemini-3-pro |
| Grok | `XAI_API_KEY` | grok-4 |
| Ollama | (none - local) | llama4:scout, qwen3-coder |

### Reranker Providers (2, v8.0+)

| Provider | Env Var | Models |
|----------|---------|--------|
| SentenceTransformers | (none - local) | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Ollama | (none - local) | (reranker models) |

---

## v8.0+ Feature Setup

### File Watcher Setup

```bash
# Enable auto-reindex on file changes
brainpalace folders add ./src --watch auto --include-code
brainpalace folders add ./docs --watch auto

# Custom debounce interval
brainpalace folders add ./src --watch auto --debounce 10
```

### Embedding Cache

Automatically enabled. Monitor with:

```bash
brainpalace cache status
brainpalace cache clear --yes  # Clear if switching providers
```

### Reranking Setup

```bash
export ENABLE_RERANKING=true
export RERANKER_PROVIDER=sentence-transformers
export RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

---

## YAML Configuration Management

Guide users through YAML config setup:

```bash
# Show current configuration
brainpalace config show

# Edit configuration interactively
brainpalace config set embedding.provider openai
brainpalace config set summarization.provider anthropic
```

Config file locations (searched in order):
1. `BRAINPALACE_CONFIG` environment variable
2. `./brainpalace.yaml` or `./config.yaml`
3. `./.brainpalace/config.yaml`
4. `~/.brainpalace/config.yaml`
5. `~/.config/brainpalace/config.yaml`

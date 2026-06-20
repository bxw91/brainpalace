---
last_validated: 2026-06-20
---

# Provider Configuration Guide

BrainPalace supports pluggable providers for embeddings and summarization. This guide covers all configuration options.

## Provider Overview

### Embedding Providers

Embeddings convert text into vector representations for semantic search.

<!--GENERATED:providers-embedding-->
| Provider | API key env var | Models (default first) |
|----------|-----------------|------------------------|
| `openai` | `OPENAI_API_KEY` | `text-embedding-3-large`, `text-embedding-3-small` |
| `cohere` | `COHERE_API_KEY` | `embed-english-v3.0`, `embed-multilingual-v3.0` |
| `ollama` | _(none — local)_ | `nomic-embed-text`, `mxbai-embed-large` |
<!--/GENERATED-->

Characteristics: OpenAI is highest-quality (3072 dims for `-large`, industry standard);
Cohere is multi-language (1024 dims); Ollama runs locally, privacy-first, no API cost.
Other supported models (not the recommended defaults): `text-embedding-ada-002` (OpenAI,
legacy), `embed-english-light-v3.0` (Cohere), `all-minilm` (Ollama).

### Summarization Providers

Summarization generates concise descriptions of code and documents during indexing.

<!--GENERATED:providers-summarization-->
| Provider | API key env var | Models (default first) |
|----------|-----------------|------------------------|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-haiku-4-5-20251001`, `claude-sonnet-4-5-20250514` |
| `openai` | `OPENAI_API_KEY` | `gpt-5-mini`, `gpt-5` |
| `gemini` | `GEMINI_API_KEY` | `gemini-3.1-flash-lite`, `gemini-3.5-flash` |
| `grok` | `XAI_API_KEY` | `grok-4`, `grok-4-fast` |
| `ollama` | _(none — local)_ | `llama4:scout`, `mistral-small3.2`, `qwen3-coder` |
<!--/GENERATED-->

Characteristics: Anthropic is code-aware and fast; OpenAI is versatile; Gemini is fast on
large contexts; Grok is conversational; Ollama runs locally, no API cost. Other supported
models: `claude-opus-4-5-20251101` (Anthropic), `gemma3` (Ollama).

## Configuration Methods

### Method 1: YAML Configuration File (Recommended)

Create a `config.yaml` file with API keys and settings. BrainPalace searches these locations in order:

1. `BRAINPALACE_CONFIG` environment variable (explicit path)
2. State dir `config.yaml` (if `BRAINPALACE_STATE_DIR`/`DOC_SERVE_STATE_DIR` set)
3. Current directory: `./config.yaml`
4. Project directory: `./.brainpalace/config.yaml`
5. XDG config (preferred global): `~/.config/brainpalace/config.yaml`
6. User home (legacy, deprecated): `~/.brainpalace/config.yaml`

**Complete example** (`~/.config/brainpalace/config.yaml`):

```yaml
# Server settings (for CLI connection)
server:
  url: "http://127.0.0.1:8000"
  port: 8000
  host: "127.0.0.1"
  auto_port: true

# Project settings
project:
  state_dir: null  # null = default (.brainpalace)
  # state_dir: "/custom/path/brainpalace"  # Custom location

# Embedding configuration
embedding:
  provider: "openai"  # openai, ollama, cohere, gemini
  model: "text-embedding-3-large"
  api_key: "sk-proj-..."  # Direct API key
  # api_key_env: "OPENAI_API_KEY"  # OR read from env var
  base_url: null  # Custom endpoint (for Ollama: http://localhost:11434/v1)

# Summarization configuration
summarization:
  provider: "anthropic"  # anthropic, openai, ollama, gemini, grok
  model: "claude-haiku-4-5-20251001"
  api_key: "sk-ant-..."  # Direct API key
  # api_key_env: "ANTHROPIC_API_KEY"  # OR read from env var
  base_url: null
```

**API key resolution order**: `api_key` field → environment variable from `api_key_env` → default env var

**Security warning**: If storing API keys in config files:
```bash
chmod 600 ~/.config/brainpalace/config.yaml  # Restrict permissions
echo "config.yaml" >> .gitignore       # Exclude from version control
```

### Method 2: Environment Variables

Set variables in your shell or `.env` file:

```bash
# Embedding configuration
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-large

# Summarization configuration
export SUMMARIZATION_PROVIDER=anthropic
export SUMMARIZATION_MODEL=claude-haiku-4-5-20251001

# API keys (as needed)
export OPENAI_API_KEY=sk-proj-...
export ANTHROPIC_API_KEY=sk-ant-...

# State directory (optional)
export BRAINPALACE_STATE_DIR=/custom/path/.brainpalace
export BRAINPALACE_URL=http://127.0.0.1:8000
```

### Method 3: .env File

Create `.brainpalace/.env` in your project:

```bash
# Provider settings
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
SUMMARIZATION_PROVIDER=anthropic
SUMMARIZATION_MODEL=claude-haiku-4-5-20251001

# API keys
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Configuration Precedence

Resolution order (highest to lowest priority):

1. **CLI options** (`--url`, `--port`)
2. **Environment variables** (`BRAINPALACE_URL`, `OPENAI_API_KEY`)
3. **Config file values** (`config.yaml`)
4. **Default values**

## Configuration Profiles

### Fully Local (No API Keys)

Best for: Privacy, air-gapped environments, no API costs

```bash
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
SUMMARIZATION_PROVIDER=ollama
SUMMARIZATION_MODEL=llama4:scout
OLLAMA_BASE_URL=http://localhost:11434
```

**Requirements:**
1. Install Ollama: https://ollama.ai
2. Pull required models:
   ```bash
   ollama pull nomic-embed-text
   ollama pull llama4:scout
   ```

### Cloud (Best Quality)

Best for: Production use, highest quality results

```bash
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
SUMMARIZATION_PROVIDER=anthropic
SUMMARIZATION_MODEL=claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Mixed (Quality + Privacy)

Best for: Quality embeddings with local summarization

```bash
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large
SUMMARIZATION_PROVIDER=ollama
SUMMARIZATION_MODEL=llama4:scout
OPENAI_API_KEY=sk-proj-...
OLLAMA_BASE_URL=http://localhost:11434
```

### Budget-Conscious

Best for: Lower API costs while maintaining quality

```bash
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
SUMMARIZATION_PROVIDER=openai
SUMMARIZATION_MODEL=gpt-5-mini
OPENAI_API_KEY=sk-proj-...
```

### Multi-Language

Best for: International content, multiple languages

```bash
EMBEDDING_PROVIDER=cohere
EMBEDDING_MODEL=embed-multilingual-v3.0
SUMMARIZATION_PROVIDER=anthropic
SUMMARIZATION_MODEL=claude-haiku-4-5-20251001
COHERE_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
```

## Provider-Specific Configuration

### OpenAI Configuration

```bash
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-large  # or text-embedding-3-small
OPENAI_API_KEY=sk-proj-...
OPENAI_ORG_ID=org-...                   # Optional: organization ID
OPENAI_BASE_URL=https://api.openai.com  # Optional: custom endpoint
```

**Available Models:**
- `text-embedding-3-large`: 3072 dimensions, highest quality
- `text-embedding-3-small`: 1536 dimensions, faster, cheaper
- `text-embedding-ada-002`: 1536 dimensions, legacy

### Cohere Configuration

```bash
EMBEDDING_PROVIDER=cohere
EMBEDDING_MODEL=embed-english-v3.0
COHERE_API_KEY=...
```

**Available Models:**
- `embed-english-v3.0`: English-optimized, 1024 dimensions
- `embed-multilingual-v3.0`: 100+ languages, 1024 dimensions
- `embed-english-light-v3.0`: Faster, smaller model

### Ollama Configuration

```bash
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
SUMMARIZATION_PROVIDER=ollama
SUMMARIZATION_MODEL=llama4:scout
OLLAMA_BASE_URL=http://localhost:11434  # Default Ollama URL
```

**Setup:**
```bash
# Install Ollama (macOS)
brew install ollama

# Install Ollama (Linux)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull embedding model
ollama pull nomic-embed-text

# Pull summarization model
ollama pull llama4:scout
```

**Available Embedding Models:**
- `nomic-embed-text`: General purpose, 768 dimensions
- `mxbai-embed-large`: High quality, 1024 dimensions
- `all-minilm`: Lightweight, fast

**Available Summarization Models:**
- `llama4:scout`: Meta's Llama 4 Scout - lightweight, fast
- `mistral-small3.2`: Mistral Small 3.2 - balanced
- `qwen3-coder`: Alibaba Qwen 3 Coder - code-focused
- `gemma3`: Google Gemma 3 - efficient
- `deepseek-coder-v3`: DeepSeek Coder V3 - code-focused

### Anthropic Configuration

```bash
SUMMARIZATION_PROVIDER=anthropic
SUMMARIZATION_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_API_KEY=sk-ant-...
```

**Available Models:**
- `claude-haiku-4-5-20251001`: Fast, cost-effective
- `claude-sonnet-4-5-20250514`: Balanced quality/speed
- `claude-opus-4-5-20251101`: Highest quality

### Gemini Configuration

```bash
SUMMARIZATION_PROVIDER=gemini
SUMMARIZATION_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=...
```

**Available Models:**
- `gemini-3.1-flash-lite`: Fast, efficient
- `gemini-3.5-flash`: Higher quality

### Grok Configuration

```bash
SUMMARIZATION_PROVIDER=grok
SUMMARIZATION_MODEL=grok-4
XAI_API_KEY=...
```

### SentenceTransformers Reranker Configuration (v8.0+)

BrainPalace supports two-stage retrieval with reranking. The reranker re-scores initial results for higher precision.

```bash
ENABLE_RERANKING=true
RERANKER_PROVIDER=sentence-transformers  # or "ollama"
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_TOP_K_MULTIPLIER=10  # Fetch 10x candidates in Stage 1
RERANKER_MAX_CANDIDATES=100   # Cap on Stage 1 results
```

**Reranker Providers:**

<!--GENERATED:providers-reranker-->
| Provider | API key env var | Models (default first) |
|----------|-----------------|------------------------|
| `sentence-transformers` | _(none — local)_ | `cross-encoder/ms-marco-MiniLM-L-6-v2`, `cross-encoder/ms-marco-MiniLM-L-12-v2` |
| `ollama` | _(none — local)_ | `llama3.2:1b` |
<!--/GENERATED-->

Both run locally with no API cost: sentence-transformers uses a fast local
cross-encoder; Ollama reranks via a local Ollama model.

**YAML Configuration:**
```yaml
reranking:
  enabled: true
  provider: "sentence-transformers"
  model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
  top_k_multiplier: 10
  max_candidates: 100
```

---

## Verifying Configuration

```bash
# Show current configuration
brainpalace config show

# Verify providers are working
brainpalace verify

# Diagnose provider config + required API keys (embedding & summarization)
brainpalace doctor
```

## Switching Providers

When switching providers, you may need to re-index documents if the embedding dimensions differ:

```bash
# Check current embedding dimensions
brainpalace status

# If switching embedding providers with different dimensions:
brainpalace reset --yes
brainpalace index /path/to/docs
```

## Troubleshooting

### API Key Issues

```
Error: Invalid API key
```

**Resolution:** Verify your API key is correct and has the necessary permissions.

### Ollama Connection Failed

```
Error: Could not connect to Ollama at http://localhost:11434
```

**Resolution:**
```bash
# Check if Ollama is running
ollama list

# Start Ollama
ollama serve
```

### Model Not Found

```
Error: Model 'model-name' not found
```

**Resolution:**
```bash
# For Ollama, pull the model
ollama pull model-name

# For cloud providers, verify model name spelling
```

### Rate Limiting

```
Error: Rate limit exceeded
```

**Resolution:**
- Wait and retry
- Use a different provider temporarily
- Upgrade your API plan

## Cost Considerations

### Embedding Costs (per 1M tokens)

| Provider | Model | Approximate Cost |
|----------|-------|------------------|
| OpenAI | text-embedding-3-large | $0.13 |
| OpenAI | text-embedding-3-small | $0.02 |
| Cohere | embed-english-v3.0 | $0.10 |
| Ollama | Any | Free (local compute) |

### Summarization Costs (per 1M tokens)

| Provider | Model | Input | Output |
|----------|-------|-------|--------|
| Anthropic | claude-haiku-4-5-20251001 | $0.80 | $4.00 |
| OpenAI | gpt-5-mini | $0.50 | $1.50 |
| Gemini | gemini-3.1-flash-lite | $0.10 | $0.40 |
| Ollama | Any | Free (local compute) |

*Prices as of 2026, subject to change.*

---
last_validated: 2026-05-30
---

# BrainPalace Installation Guide

Complete installation options for BrainPalace with pluggable providers and GraphRAG support.

## Prerequisites

- Python 3.10 or higher
- pip, pipx, uv, or conda (package manager)
- Optional: Ollama for local embeddings/summarization

---

## Installation Methods

Choose the best method for your workflow:

| Method | Best For | Scope | Requires Activation |
|--------|----------|-------|---------------------|
| pipx (recommended) | Most users | Global (isolated) | No |
| uv | Power users | Global (isolated) | No |
| pip (venv) | Project-scoped | Project | Yes |
| conda | Data science | Environment | Yes |

---

## Method 1: pipx (Recommended)

**Best for:** Most users who want a simple, global CLI installation

```bash
# Install pipx (if needed)
python -m pip install --user pipx
python -m pipx ensurepath

# Install BrainPalace
pipx install brainpalace-cli

# Verify
brainpalace --version

# Upgrade later
pipx upgrade brainpalace-cli
```

---

## Method 2: uv

**Best for:** Power users, those already using uv

```bash
# Install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install BrainPalace
uv tool install brainpalace-cli

# Verify
brainpalace --version

# Upgrade later
uv tool upgrade brainpalace-cli
```

---

## Method 3: pip with Virtual Environment

**Best for:** Project-scoped installations, CI/CD

```bash
# Create and activate venv
python -m venv .venv
source .venv/bin/activate  # Linux/macOS

# Install BrainPalace
pip install brainpalace-rag brainpalace-cli

# Verify
brainpalace --version
```

**Note:** Must activate venv each time: `source .venv/bin/activate`

---

## Method 4: Conda

**Best for:** Data science users

```bash
# Create conda environment
conda create -n brainpalace python=3.12 -y
conda activate brainpalace

# Install BrainPalace (pip inside conda)
pip install brainpalace-rag brainpalace-cli

# Verify
brainpalace --version
```

**Note:** Must activate env each time: `conda activate brainpalace`

---

## Installation Extras

### Basic Installation

Installs core RAG functionality with hybrid search (BM25 + semantic):

```bash
pip install brainpalace-rag brainpalace-cli
```

### With GraphRAG Support

Includes knowledge graph capabilities with SimplePropertyGraphStore:

```bash
pip install "brainpalace-rag[graphrag]" brainpalace-cli
```

### With All Features

Includes GraphRAG with Kuzu database backend for production use:

```bash
pip install "brainpalace-rag[graphrag-all]" brainpalace-cli
```

## Installation Extras Reference

| Extra | Includes | Use Case |
|-------|----------|----------|
| (none) | Core RAG, ChromaDB, BM25, LlamaIndex | Basic document search |
| `graphrag` | + langextract, SimplePropertyGraphStore | Development GraphRAG |
| `graphrag-all` | + Kuzu database | Production GraphRAG |

---

## Development Installation

For contributors or local development:

```bash
# Clone repository
git clone https://github.com/bxw91/brainpalace.git
cd brainpalace

# Install in editable mode
pip install -e "./brainpalace-server[dev]"
pip install -e "./brainpalace-cli[dev]"

# Or use Poetry
cd brainpalace-server && poetry install
cd ../brainpalace-cli && poetry install
```

---

## Verifying Installation

```bash
# Check CLI version
brainpalace --version

# Check server package
python -c "import brainpalace_server; print(brainpalace_server.__version__)"

# Verify all dependencies
brainpalace verify
```

---

## Quick Reference

| Method | Install Command | Upgrade Command |
|--------|-----------------|-----------------|
| pipx | `pipx install brainpalace-cli` | `pipx upgrade brainpalace-cli` |
| uv | `uv tool install brainpalace-cli` | `uv tool upgrade brainpalace-cli` |
| pip | `pip install brainpalace-rag brainpalace-cli` | `pip install --upgrade ...` |
| conda | `pip install ...` (in conda env) | `pip install --upgrade ...` |

---

## System Requirements

### Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ |
| RAM | 2GB (4GB recommended) |
| Disk | 500MB + index storage |

### With GraphRAG

| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ |
| RAM | 4GB (8GB recommended) |
| Disk | 1GB + index storage |

---

## Troubleshooting Installation

### Command Not Found

**pipx:**
```bash
python -m pipx ensurepath
# Restart terminal
```

**uv:**
```bash
uv tool list  # Verify installed
# Restart terminal
```

**pip (venv):**
```bash
source .venv/bin/activate  # Must activate first
```

### pip installation fails

```bash
# Upgrade pip first
pip install --upgrade pip

# Try with --no-cache-dir
pip install --no-cache-dir brainpalace-rag brainpalace-cli
```

### Dependency conflicts

Use a virtual environment (Method 3) or pipx (Method 1) to isolate dependencies.

### ChromaDB build issues

On some systems, ChromaDB may require additional build tools:

```bash
# Ubuntu/Debian
sudo apt-get install build-essential

# macOS
xcode-select --install

# Then reinstall
pip install --no-cache-dir brainpalace-rag
```

### Kuzu installation issues (graphrag-all)

Kuzu requires a C++ compiler:

```bash
# Ubuntu/Debian
sudo apt-get install g++

# macOS (already included with Xcode)
xcode-select --install
```

---

## Uninstallation

| Method | Command |
|--------|---------|
| pipx | `pipx uninstall brainpalace-cli` |
| uv | `uv tool uninstall brainpalace-cli` |
| pip | `pip uninstall brainpalace-rag brainpalace-cli -y` |
| conda | `pip uninstall brainpalace-rag brainpalace-cli -y` (in conda env) |

---

## Multi-Runtime Installation (v9.0+)

BrainPalace supports installing its plugin into multiple AI coding assistant runtimes. After installing the CLI, use the `install-agent` command to deploy the plugin:

```bash
# Install for Claude Code (default)
brainpalace install-agent --agent claude

# Install for OpenCode
brainpalace install-agent --agent opencode

# Install for Gemini
brainpalace install-agent --agent gemini

# Install for Codex (skill-directory format with AGENTS.md)
brainpalace install-agent --agent codex

# Install for any skill-based runtime (requires --dir)
brainpalace install-agent --agent skill-runtime --dir /path/to/skills

# Preview what will be installed (no files written)
brainpalace install-agent --agent claude --dry-run

# Install globally (user-level) instead of project-level
brainpalace install-agent --agent claude --scope global
```

### Supported Runtimes

| Runtime | Install Dir (project) | Format |
|---------|----------------------|--------|
| `claude` | `.claude/plugins/brainpalace` | Claude plugin (commands, skills, agents) |
| `opencode` | `.opencode/plugins/brainpalace` | OpenCode plugin format |
| `gemini` | `.gemini/plugins/brainpalace` | Gemini plugin format |
| `codex` | `.codex/skills/brainpalace` | Skill directories + AGENTS.md |
| `skill-runtime` | (requires `--dir`) | Generic skill directories |

### Uninstalling

```bash
# Remove plugin for a specific runtime
brainpalace uninstall --agent claude

# Remove from global scope
brainpalace uninstall --agent claude --scope global
```

---

## Key Features by Version

| Version | Key Features |
|---------|-------------|
| v7.0 | Folder management, file type presets, content injection, chunk eviction |
| v8.0 | File watcher (auto-reindex), embedding cache, setup wizard, query cache |
| v9.0+ | Multi-runtime install (5 runtimes), pluggable providers (7 providers) |

---

## Next Steps

After installation:

1. [Configure providers](provider-configuration.md)
2. [Initialize your project](../SKILL.md#server-management)
3. [Index documents](../SKILL.md#server-management)
4. [Start searching](../SKILL.md#search-modes)

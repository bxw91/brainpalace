---
last_validated: 2026-06-18
---

# BrainPalace Installation Guide

## Overview

This guide covers the complete installation process for BrainPalace, including multiple installation methods, prerequisites, and verification steps.

## Prerequisites

### Python 3.10+

BrainPalace requires Python 3.10 or higher.

**Check Python Version:**
```bash
python --version
# or
python3 --version
```

**Install Python (if needed):**

| Platform | Command |
|----------|---------|
| macOS | `brew install python@3.11` |
| Ubuntu/Debian | `sudo apt install python3.11` |
| Windows | Download from python.org |
| uv | `uv python install 3.12` |

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

pipx installs the CLI globally while keeping dependencies isolated in their own virtual environment.

### Install pipx

```bash
# Check if pipx is installed
pipx --version

# Install pipx (if needed)
python -m pip install --user pipx
python -m pipx ensurepath
```

Restart your terminal after installing pipx.

### Install BrainPalace

```bash
pipx install brainpalace-cli
```

### Verify

```bash
brainpalace --version
```

### Upgrade

```bash
pipx upgrade brainpalace-cli
```

### Uninstall

```bash
pipx uninstall brainpalace-cli
```

---

## Method 2: uv

**Best for:** Power users, those already using uv, or wanting fast installs

uv is a modern, Rust-based Python package installer that's very fast.

### Install uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

### Install BrainPalace

```bash
uv tool install brainpalace-cli
```

### Verify

```bash
brainpalace --version
```

### Upgrade

```bash
uv tool upgrade brainpalace-cli
```

### Uninstall

```bash
uv tool uninstall brainpalace-cli
```

---

## Method 3: pip with Virtual Environment

**Best for:** Project-scoped installations, CI/CD environments

This method keeps BrainPalace local to a specific project directory.

### Create Virtual Environment

```bash
# Create venv
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate
```

### Install BrainPalace

```bash
pip install brainpalace-rag brainpalace-cli
```

### Verify

```bash
brainpalace --version
```

**Note:** You must activate the virtual environment before using BrainPalace:
```bash
source .venv/bin/activate  # Run this each time
```

### Upgrade

```bash
source .venv/bin/activate
pip install --upgrade brainpalace-rag brainpalace-cli
```

### Uninstall

```bash
pip uninstall brainpalace-rag brainpalace-cli
```

---

## Method 4: Conda

**Best for:** Data science users already in the conda ecosystem

BrainPalace is distributed on PyPI (not conda-forge), so you install it with pip inside a conda environment.

### Create Conda Environment

```bash
conda create -n brainpalace python=3.12 -y
conda activate brainpalace
```

### Install BrainPalace

```bash
pip install brainpalace-rag brainpalace-cli
```

### Verify

```bash
brainpalace --version
```

**Note:** Activate the conda environment before using BrainPalace:
```bash
conda activate brainpalace  # Run this each time
```

### Upgrade

```bash
conda activate brainpalace
pip install --upgrade brainpalace-rag brainpalace-cli
```

---

## Post-Installation Verification

After installation, verify everything is working:

```bash
# Check CLI is available
brainpalace --help

# Check version
brainpalace --version
```

Expected help output:
```
Usage: brainpalace [OPTIONS] COMMAND [ARGS]...

  BrainPalace CLI - Document search and indexing management

Options:
  --version  Show version
  --help     Show this message and exit.

Commands:
  index   Index documents
  init    Initialize project
  list    List running instances
  query   Search documents
  reset   Clear index
  start   Start server
  status  Check server status
  stop    Stop server
```

---

## Quick Reference

| Method | Install Command | Upgrade Command |
|--------|-----------------|-----------------|
| pipx | `pipx install brainpalace-cli` | `pipx upgrade brainpalace-cli` |
| uv | `uv tool install brainpalace-cli` | `uv tool upgrade brainpalace-cli` |
| pip | `pip install brainpalace-rag brainpalace-cli` | `pip install --upgrade brainpalace-rag brainpalace-cli` |
| conda | `pip install ...` (in conda env) | `pip install --upgrade ...` |

---

## Troubleshooting Installation

### Issue: Command Not Found

**Symptom:** `brainpalace: command not found`

**Solutions by method:**

**pipx:**
```bash
python -m pipx ensurepath
# Restart terminal
```

**uv:**
```bash
uv tool list  # Verify it's installed
# Restart terminal
```

**pip (venv):**
```bash
source .venv/bin/activate  # Must activate first
which brainpalace
```

**conda:**
```bash
conda activate brainpalace  # Must activate first
which brainpalace
```

### Issue: Permission Denied

**Symptom:** `Permission denied` during installation

**Solutions:**

1. **Use pipx (recommended):** Avoids permission issues entirely
2. **Use user installation:** `pip install --user brainpalace-cli`
3. **Use virtual environment:** See Method 3 above
4. **Never use sudo with pip**

### Issue: Module Not Found

**Symptom:** `ModuleNotFoundError` when running

**Solutions:**

```bash
# Reinstall packages
pip install --force-reinstall brainpalace-rag brainpalace-cli

# Check Python environment
which python
pip list | grep brainpalace
```

### Issue: pip Not Found

**Symptom:** `pip: command not found`

**Solutions:**

```bash
# Use python -m pip
python -m pip install brainpalace-rag brainpalace-cli

# Or install pip
python -m ensurepip --upgrade
```

### Issue: Python Version Too Low

**Symptom:** Installation fails with Python version error

**Solutions:**

```bash
# Install newer Python
brew install python@3.11  # macOS
sudo apt install python3.11  # Ubuntu
uv python install 3.12  # Using uv

# Or use conda
conda create -n brainpalace python=3.12
```

### Issue: SSL Certificate Error

**Symptom:** SSL errors during installation

**Solutions:**

```bash
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org brainpalace-rag brainpalace-cli
```

---

## Dependencies

BrainPalace installs these major dependencies:

| Package | Purpose |
|---------|---------|
| FastAPI | REST API server |
| ChromaDB | Vector database |
| LlamaIndex | Document processing |
| OpenAI | Embeddings API |
| Click | CLI framework |
| Rich | CLI formatting |

## System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 512MB | 2GB |
| Disk | 500MB | 2GB |
| Python | 3.10 | 3.11+ |

---

## Multi-Runtime Installation (v9.0+)

After installing the CLI, deploy the BrainPalace plugin to your AI coding assistant:

```bash
# Install for Claude Code (default)
brainpalace install-agent --agent claude

# Install for OpenCode
brainpalace install-agent --agent opencode

# Install for Gemini
brainpalace install-agent --agent gemini

# Install for Codex (generates skill directories + AGENTS.md)
brainpalace install-agent --agent codex

# Install for any skill-based runtime (requires --dir)
brainpalace install-agent --agent skill-runtime --dir /path/to/skills

# Dry run to preview files
brainpalace install-agent --agent claude --dry-run

# Global (user-level) installation
brainpalace install-agent --agent claude --global
```

### Supported Runtimes

| Runtime | Project Install Dir | Format |
|---------|-------------------|--------|
| `claude` | `.claude/plugins/brainpalace` | Claude plugin |
| `opencode` | `.opencode/plugins/brainpalace` | OpenCode plugin |
| `gemini` | `.gemini/plugins/brainpalace` | Gemini plugin |
| `codex` | `.codex/skills/brainpalace` | Skill dirs + AGENTS.md |
| `skill-runtime` | (requires `--dir`) | Generic skill dirs |

### Uninstalling

There is no CLI to remove an installed plugin (`install-agent` only installs).
Delete the install dir directly — project scope + global scope:

```bash
rm -rf .claude/plugins/brainpalace    ~/.claude/plugins/brainpalace
rm -rf .opencode/plugins/brainpalace  ~/.config/opencode/plugins/brainpalace
rm -rf .gemini/plugins/brainpalace    ~/.config/gemini/plugins/brainpalace
rm -rf .codex/skills/brainpalace      ~/.codex/skills/brainpalace
```

---

## Complete teardown (remove all state)

**Easiest:** `brainpalace uninstall` (guided — stops servers, removes plugins +
MCP entries, deletes selected per-project + global state, then prints any
leftover step). The manual sequence below is for when the binary is already
gone or you want full control.

The per-method `### Uninstall` blocks above remove only the **package**, and the
block above removes only the **plugin**. Neither touches running servers,
per-project state, global dirs, MCP configs, or your shell rc. For a full
removal, run in order — stop/enumerate servers **before** removing the binary:

```bash
# 1. Stop every server (needs the binary — do it first) and note its project.
brainpalace list
brainpalace stop --path <project>          # repeat per project

# 2. Remove the plugin dirs from each runtime (see "Uninstalling" above).

# 3. Uninstall the package (see the per-method "Uninstall" blocks above).

# 4. Delete per-project state — ⚠️ holds archived raw transcripts (secrets).
rm -rf <project>/.brainpalace             # one per initialised project

# 5. Delete global state (honour $XDG_* overrides if set).
rm -rf ~/.config/brainpalace ~/.local/state/brainpalace \
       ~/.local/share/brainpalace ~/.brainpalace

# 6. Remove the `brainpalace` entry from any MCP client config (project + $HOME):
#    .vscode/mcp.json .cursor/mcp.json .zed/settings.json
#    .cline/mcp.json  .continue/mcp.yaml .kilo/kilo.jsonc

# 7. Remove any `export <PROVIDER>_API_KEY=…` you added to your shell rc.
```

Full prose version: [docs/INSTALL.md → Full uninstall (teardown)](../../../../docs/INSTALL.md#full-uninstall-teardown).

---

## Key Features by Version

| Version | Key Features |
|---------|-------------|
| v7.0 | Folder management (`folders add/list/remove`), file type presets (`types list`), content injection (`inject`), chunk eviction |
| v8.0 | File watcher (auto-reindex on file changes), embedding cache, setup wizard, query cache, reranking |
| v9.0+ | Multi-runtime install (5 runtimes), pluggable providers (7 providers), generic skill-runtime converter |

---

## Next Steps

After installation:
1. [Configure providers](configuration-guide.md) (API keys or Ollama)
2. Initialize project: `/brainpalace:brainpalace-init`
3. Start server: `/brainpalace:brainpalace-start`
4. Index documents: `/brainpalace:brainpalace-index /path/to/docs`

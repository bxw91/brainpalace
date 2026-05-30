---
name: brainpalace-version
description: Show current version and manage BrainPalace versions
parameters:
  - name: action
    description: Action to perform (show, list, install, upgrade)
    required: false
    default: show
  - name: version
    description: Specific version for install action
    required: false
skills:
  - using-brainpalace
last_validated: 2026-03-16
---

# BrainPalace Version Management

## Purpose

Shows current BrainPalace version and manages version installations. Use this plugin command to check versions, list available releases, upgrade to latest, or install specific versions.

**Note:** The CLI provides `brainpalace --version` for version display. The list, install, and upgrade actions described below are plugin-level workflows that execute pip/uv commands.

## Usage

```
/brainpalace:brainpalace-version [action] [--version <ver>]
```

### Actions

| Action | Description |
|--------|-------------|
| `show` | Show current installed version (default) |
| `list` | List all available versions |
| `install` | Install a specific version |
| `upgrade` | Upgrade to latest version |

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| action | No | Action to perform (default: show) |
| --version | For install | Version to install (e.g., 3.0.0, 2.0.0) |

## Execution

### Show Current Version (Default)

The CLI provides a built-in version flag:

```bash
# Show CLI version
brainpalace --version
```

To check installed Python package versions:

```bash
pip show brainpalace-rag brainpalace-cli | grep -E "^(Name|Version)"
```

### List Available Versions

```bash
# List all available versions on PyPI
pip index versions brainpalace-rag 2>/dev/null | head -20
```

### Install Specific Version

```bash
# Install specific version (using uv for speed)
uv pip install brainpalace-rag==X.Y.Z brainpalace-cli==X.Y.Z

# Or with pip
pip install brainpalace-rag==X.Y.Z brainpalace-cli==X.Y.Z
```

### Upgrade to Latest

```bash
# Using uv (preferred)
uv pip install --upgrade brainpalace-rag brainpalace-cli

# Or with pip
pip install --upgrade brainpalace-rag brainpalace-cli
```

## Output

### Version Show Output

```
BrainPalace Version Information
===============================

CLI Version: $VERSION
Server Package: $VERSION

Components:
- brainpalace-rag: $VERSION
- brainpalace-cli: $VERSION

Features:
- Hybrid Search: Enabled
- GraphRAG: Enabled (requires ENABLE_GRAPH_INDEX=true)
- Pluggable Providers: Yes

Python: 3.11.x
Platform: darwin (arm64)
```

Note: Run version resolver to get current version:
```bash
VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
```

### Version List Output

```
Available BrainPalace Versions
==============================

Latest: $LATEST (resolved from PyPI)

Recent Versions:
- 3.0.0  (2025-02) - Job queue, async indexing
- 2.0.0  (2024-12) - Pluggable providers, GraphRAG
- 1.4.0  (2024-11) - Graph search, multi-mode fusion
- 1.3.0  (2024-10) - AST-aware code ingestion

To install a specific version:
VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
pip install brainpalace-rag==$VERSION brainpalace-cli==$VERSION
```

### Install Output

```
Installing BrainPalace version $VERSION...

pip install brainpalace-rag==$VERSION brainpalace-cli==$VERSION

Successfully installed:
- brainpalace-rag $VERSION
- brainpalace-cli $VERSION

Note: You may need to re-index documents after version changes.
Run: brainpalace reset --yes && brainpalace index /path/to/docs
```

### Upgrade Output

```
Upgrading BrainPalace to latest version...

pip install --upgrade brainpalace-rag brainpalace-cli

Upgraded from X.Y.Z to $LATEST

Check release notes for changes:
https://github.com/bxw91/brainpalace/releases

Migration steps:
1. Review breaking changes in release notes
2. Update provider environment variables if needed
3. Re-index documents for new features
```

## Version Compatibility

### Package Alignment

Keep both packages on the same version:

| RAG Version | CLI Version | Compatible |
|-------------|-------------|------------|
| X.Y.Z | X.Y.Z | Yes |
| X.Y.Z | A.B.C | No - versions must match |

### Index Compatibility

| From | To | Index Action |
|------|-----|--------------|
| N.x | N+1.0 | Re-index usually required |
| N.x.y | N.x.z | Usually compatible |

### Migration Between Major Versions

When upgrading between major versions:

```bash
# 1. Stop server
brainpalace stop

# 2. Upgrade
pip install --upgrade brainpalace-rag brainpalace-cli

# 3. Configure new provider settings
export EMBEDDING_PROVIDER=openai
export EMBEDDING_MODEL=text-embedding-3-large
export SUMMARIZATION_PROVIDER=anthropic
export SUMMARIZATION_MODEL=claude-haiku-4-5-20251001

# 4. Re-index
brainpalace reset --yes
brainpalace start
brainpalace index /path/to/docs
```

## Error Handling

### Version Not Found

```
Error: Version '9.9.9' not found
```

**Resolution:** Use `/brainpalace:brainpalace-version list` to see available versions

### Network Error

```
Error: Could not connect to PyPI
```

**Resolution:** Check internet connection and try again

### Permission Error

```
Error: Permission denied installing packages
```

**Resolution:**
```bash
# Use user installation
pip install --user brainpalace-rag brainpalace-cli

# Or use virtual environment
python -m venv venv
source venv/bin/activate
pip install brainpalace-rag brainpalace-cli
```

### Version Mismatch

```
Warning: Package version mismatch
- brainpalace-rag: X.Y.Z
- brainpalace-cli: A.B.C
```

**Resolution:**
```bash
# Get latest version
VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
pip install brainpalace-rag==$VERSION brainpalace-cli==$VERSION
```

## Related Commands

- `/brainpalace:brainpalace-install` - Install BrainPalace packages
- `/brainpalace:brainpalace-verify` - Verify installation
- `/brainpalace:brainpalace-status` - Show server status

---
last_validated: 2026-07-23
---

# BrainPalace Version Management

Guide for installing, upgrading, and managing BrainPalace versions.

## Current Version

Resolve the latest version dynamically from PyPI:

```bash
VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
echo "Latest: $VERSION"
```

### Version History

| Version | Release Date | Key Features |
|---------|--------------|--------------|
| 9.1.0 | 2026-03 | Generic skill-runtime converter, Codex adapter, AGENTS.md generation |
| 9.0.0 | 2026-03 | Multi-runtime install (claude, opencode, gemini, codex, skill-runtime) |
| 8.0.0 | 2026-03 | File watcher, embedding cache, setup wizard, query cache, reranking |
| 7.0.0 | 2026-03 | Folder management, file type presets, content injection, chunk eviction |
| 3.0.0 | 2025-02 | Job queue, async indexing, server-side processing |
| 2.0.0 | 2024-12 | Pluggable providers, GraphRAG, multi-instance |
| 1.4.0 | 2024-11 | Graph search mode, multi-mode fusion |
| 1.3.0 | 2024-10 | AST-aware code ingestion |

## Checking Version

```bash
# CLI version
brainpalace --version

# Server package version
python -c "import brainpalace_server; print(brainpalace_server.__version__)"

# Both packages
pip show brainpalace-rag brainpalace-cli
```

## Installing Specific Versions

### Latest Stable (Recommended)

```bash
# Resolve and install latest
VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
pip install brainpalace-rag==$VERSION brainpalace-cli==$VERSION
```

### Specific Version

```bash
# Install exact version (replace $VERSION with desired version)
pip install brainpalace-rag==$VERSION brainpalace-cli==$VERSION
```

### Version Range

```bash
# Compatible with 3.x
pip install "brainpalace-rag>=3.0.0,<4.0.0"

# Minimum version
pip install "brainpalace-rag>=3.0.0"
```

## Listing Available Versions

```bash
# List all available versions
pip index versions brainpalace-rag

# Alternative with pip
pip install brainpalace-rag==  # Shows error with all versions listed
```

## Upgrading

### Upgrade to Latest (recommended)

```bash
brainpalace update
```

Auto-detects pipx / uv / pip and runs the matching upgrade. It prints a
pre-flight notice listing any running servers + the control-plane dashboard
(they keep serving the OLD code until restarted), then — after the upgrade —
offers to restart them so they load the new version (`--no-restart` to skip,
`--yes` to auto-confirm).

### Upgrade with raw pip

```bash
pip install --upgrade brainpalace-rag brainpalace-cli
# then restart any running instances yourself:
brainpalace stop && brainpalace start
```

### Upgrade to Specific Version

```bash
# Resolve latest first
VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
pip install --upgrade brainpalace-rag==$VERSION brainpalace-cli==$VERSION
```

### Check for Updates

```bash
# Check if updates are available
pip list --outdated | grep brainpalace
```

## Downgrading

To downgrade to a previous version:

```bash
# Set target version
TARGET_VERSION="X.Y.Z"  # e.g., 2.0.0

# Downgrade to specific version
pip install brainpalace-rag==$TARGET_VERSION brainpalace-cli==$TARGET_VERSION

# Force reinstall if needed
pip install --force-reinstall brainpalace-rag==$TARGET_VERSION
```

### Migration Considerations

When downgrading, be aware of:

1. **Index Compatibility**: Newer indexes may not work with older versions
2. **Configuration**: New config options won't be recognized
3. **Features**: New features won't be available

**Recommended Steps:**
```bash
# 1. Set target version
TARGET_VERSION="X.Y.Z"

# 2. Stop server
brainpalace stop

# 3. Backup configuration
cp -r .brainpalace .brainpalace.backup

# 4. Reset index (if needed)
brainpalace reset --yes

# 5. Downgrade
pip install brainpalace-rag==$TARGET_VERSION brainpalace-cli==$TARGET_VERSION

# 6. Re-index
brainpalace start
brainpalace index /path/to/docs
```

## Version Compatibility

### Package Alignment

Always keep `brainpalace-rag` and `brainpalace-cli` on the same version:

| RAG Version | CLI Version | Compatible |
|-------------|-------------|------------|
| X.Y.Z | X.Y.Z | Yes |
| X.Y.Z | A.B.C | No - versions must match |

### Python Version Compatibility

| BrainPalace | Python |
|-------------|--------|
| 3.x | 3.10, 3.11, 3.12 |
| 2.x | 3.10, 3.11, 3.12 |
| 1.x | 3.10, 3.11 |

### Index Compatibility

Indexes created with one version may not be compatible with another:

| From Version | To Version | Index Compatible |
|--------------|------------|------------------|
| N.x | N+1.0 | Re-index usually required |
| N.x.y | N.x.z | Usually compatible |

## Version Pinning

### In requirements.txt

```text
# Pin to specific version (resolve latest first)
brainpalace-rag==X.Y.Z
brainpalace-cli==X.Y.Z
```

### In pyproject.toml

```toml
[project]
dependencies = [
    "brainpalace-rag>=3.0.0,<4.0.0",
    "brainpalace-cli>=3.0.0,<4.0.0",
]
```

### In Poetry

```toml
[tool.poetry.dependencies]
brainpalace-rag = "^3.0.0"
brainpalace-cli = "^3.0.0"
```

## Development Versions

### Installing Pre-release

```bash
pip install --pre brainpalace-rag brainpalace-cli
```

### Installing from Git

```bash
# Latest main branch
pip install git+https://github.com/bxw91/brainpalace.git#subdirectory=brainpalace-server
pip install git+https://github.com/bxw91/brainpalace.git#subdirectory=brainpalace-cli

# Specific branch
pip install git+https://github.com/bxw91/brainpalace.git@feature-branch#subdirectory=brainpalace-server
```

## Release Notes

### v9.1.0

**New Features:**
- Generic skill-runtime converter for any skill-based AI assistant
- Codex named adapter with AGENTS.md generation
- `--dry-run` support for all runtime installs

### v9.0.0

**New Features:**
- Multi-runtime plugin installation (`install-agent` command)
- Support for 5 runtimes: Claude, OpenCode, Gemini, Codex, skill-runtime
- Plugin uninstall command
- Project and global scope installation

### v8.0.0

**New Features:**
- File watcher for automatic re-indexing on file changes
- Embedding cache (two-tier: in-memory LRU + SQLite disk)
- Query cache with configurable TTL
- Reranking with SentenceTransformers and Ollama providers
- Setup wizard for interactive configuration

### v7.0.0

**New Features:**
- Folder management (`folders add/list/remove`)
- File type presets (`types list`, `--include-type`)
- Content injection (`inject` command with custom scripts)
- Chunk eviction for folder removal

### v3.0.0

**New Features:**
- Server-side job queue for async indexing
- Background job processing
- Job status tracking and cancellation
- Improved performance for large document sets

**Breaking Changes:**
- Job queue API changes
- Index format may require re-indexing

For full release notes, see: https://github.com/bxw91/brainpalace/releases

### v2.0.0

**New Features:**
- Pluggable embedding providers (OpenAI, Cohere, Ollama)
- Pluggable summarization providers (Anthropic, OpenAI, Gemini, Grok, Ollama)
- Fully local mode with Ollama (no API keys required)
- Enhanced GraphRAG support

### v1.4.0

**Features:**
- Graph search mode
- Multi-mode fusion search
- Improved entity extraction

### v1.3.0

**Features:**
- AST-aware code ingestion
- Support for Python, TypeScript, JavaScript, Java, Go, Rust, C, C++
- Improved code summarization

### v1.2.0

**Features:**
- Multi-instance architecture
- Per-project isolation
- Automatic server discovery

## Support Lifecycle

| Version | Status | Support Until |
|---------|--------|---------------|
| 9.x | Active | Current |
| 8.x | Maintenance | 2026-12 |
| 7.x | Maintenance | 2026-09 |
| 3.0.x | End of Life | - |
| 2.0.x | End of Life | - |
| 1.x | End of Life | - |

**Active**: Full support, new features
**Maintenance**: Security fixes only
**End of Life**: No support

# BrainPalace CLI

> Command-line interface for managing AI agent memory and knowledge retrieval with the **BrainPalace** RAG server.

**BrainPalace** (formerly doc-serve) is an intelligent document indexing and semantic search system designed to give AI agents long-term memory. This CLI provides a convenient way to manage your BrainPalace server and knowledge base.

[![PyPI version](https://badge.fury.io/py/brainpalace-cli.svg)](https://pypi.org/project/brainpalace-cli/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why BrainPalace?

AI agents need persistent memory to be truly useful. BrainPalace provides the retrieval infrastructure that enables context-aware, knowledge-grounded AI interactions.

### Search Capabilities

| Search Type | Description | Best For |
|-------------|-------------|----------|
| **Semantic Search** | Natural language queries using OpenAI embeddings | Conceptual questions, related content |
| **Keyword Search (BM25)** | Traditional keyword matching with TF-IDF ranking | Exact matches, technical terms |
| **Hybrid Search** | Combines vector + BM25 approaches | General-purpose queries |
| **GraphRAG** | Knowledge graph retrieval | Understanding relationships |

## Installation

**Canonical path:** the guided installer installs the CLI + server, configures
a provider, and offers to wire your AI coding assistant(s) — Claude Code,
Codex, OpenCode, Antigravity, skill-runtime — all in one run:

```bash
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/setup.sh | bash
```

Just this package, via pip:

```bash
pip install brainpalace-cli
```

## Quick Start

```bash
brainpalace init          # Initialize project
brainpalace start         # Start server
brainpalace index ./docs  # Index documents
brainpalace query "search term"
```

> **Note**: The legacy command `doc-svr-ctl` is still available but deprecated. Please use `brainpalace` for new installations.

## Development Installation

```bash
cd brainpalace-cli
poetry install
```

## Usage

```bash
# Check server status
brainpalace status

# Search documents
brainpalace query "how to use python"

# Index documents from a folder
brainpalace index ./docs

# Reset/clear the index
brainpalace reset --yes
```

## Configuration

Set the server URL via environment variable:

```bash
export BRAINPALACE_URL=http://localhost:8000
```

Or use the `--url` flag:

```bash
brainpalace --url http://localhost:8000 status
```

> **Note**: The legacy environment variable `DOC_SERVE_URL` is still supported for backwards compatibility.

## Commands

### Server Management

| Command | Description |
|---------|-------------|
| `init` | Initialize project for BrainPalace (creates `.claude/brainpalace/`) |
| `start` | Start the BrainPalace server for current project |
| `stop` | Stop the running server |
| `list` | List all running BrainPalace instances |
| `status` | Check server health and indexing status |

### Data Management

| Command | Description |
|---------|-------------|
| `query` | Search indexed documents |
| `index` | Start indexing documents from a folder |
| `reset` | Clear all indexed documents |

## Options

All commands support:
- `--url` - Server URL (or `BRAINPALACE_URL` / `DOC_SERVE_URL` env var)
- `--json` - Output as JSON for scripting

## Example Workflow

```bash
# 1. Initialize a new project
cd my-project
brainpalace init

# 2. Start the server
brainpalace start

# 3. Index your documentation
brainpalace index ./docs ./src

# 4. Query your knowledge base
brainpalace query "How does authentication work?"

# 5. Stop when done
brainpalace stop
```

## Documentation

- [User Guide](https://github.com/bxw91/brainpalace/wiki/User-Guide) - Getting started and usage
- [Developer Guide](https://github.com/bxw91/brainpalace/wiki/Developer-Guide) - Contributing and development
- [API Reference](https://github.com/bxw91/brainpalace/wiki/API-Reference) - Full API documentation

## Release Information

- **Current Version**: See [pyproject.toml](./pyproject.toml)
- **Release Notes**: [GitHub Releases](https://github.com/bxw91/brainpalace/releases)
- **Changelog**: [Latest Release](https://github.com/bxw91/brainpalace/releases/latest)

## Related Packages

- [brainpalace-rag](https://pypi.org/project/brainpalace-rag/) - The RAG server that powers BrainPalace

## License

MIT

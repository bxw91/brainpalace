---
last_validated: 2026-06-11
---

# BrainPalace Developer Guide

This guide covers setting up a development environment, understanding the architecture, and contributing to BrainPalace.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Monorepo Structure](#monorepo-structure)
- [Quick Start for Developers](#quick-start-for-developers)
- [Task Commands](#task-commands)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Multi-Instance Architecture](#multi-instance-architecture)
- [Code Ingestion & Language Support](#code-ingestion-language-support)

---

## Architecture Overview

BrainPalace is a RAG (Retrieval-Augmented Generation) system for semantic search across documentation and source code.

```mermaid
flowchart TB
    subgraph Clients["Client Layer"]
        CLI["brainpalace<br/>(Click CLI)"]
        Skill["Claude Skill<br/>(REST Client)"]
        API_Client["External Apps<br/>(HTTP/REST)"]
    end

    subgraph Server["brainpalace-server"]
        subgraph API["REST API Layer"]
            FastAPI["FastAPI<br/>/health, /query, /index"]
        end

        subgraph Services["Service Layer"]
            IndexService["Indexing Service"]
            QueryService["Query Service"]
        end

        subgraph Indexing["Content Processing"]
            Loader["Document & Code Loader<br/>(LlamaIndex + Tree-sitter)"]
            Chunker["AST-Aware Chunking<br/>(Stable Hash ID)"]
            Embedder["Embedding Generator<br/>(+ LLM Summaries)"]
        end

        subgraph AI["AI Models"]
            OpenAI["OpenAI Embeddings<br/>(text-embedding-3-large)"]
            Claude["Claude Haiku<br/>(Summarization)"]
        end

        subgraph Storage["Vector Storage"]
            ChromaDB["ChromaDB<br/>(Vector Store)"]
        end
    end

    subgraph Documents["Content Sources"]
        MD["Markdown Files"]
        TXT["Text Files"]
        PDF["PDF Files"]
        Code["Source Code<br/>10+ Languages"]
    end

    CLI -->|HTTP| FastAPI
    Skill -->|HTTP| FastAPI
    API_Client -->|HTTP| FastAPI

    FastAPI --> IndexService
    FastAPI --> QueryService

    IndexService --> Loader
    Loader --> Documents
    Loader --> Chunker
    Chunker --> Embedder
    Embedder --> OpenAI
    Embedder --> ChromaDB

    QueryService --> Embedder
    QueryService --> ChromaDB
```

---

## Monorepo Structure

| Package | Directory | Description |
|---------|-----------|-------------|
| `brainpalace-server` | `brainpalace-server/` | FastAPI REST API backend |
| `brainpalace-cli` | `brainpalace-cli/` | Click-based CLI management tool |
| `brainpalace-skill` | `brainpalace-skill/` | Claude Code skill definition |
| `e2e` | `e2e/` | End-to-end integration tests |

### Notable sub-modules

| Module | Path | Description |
|---|---|---|
| `brainpalace_cli.mcp_server` | `brainpalace-cli/brainpalace_cli/mcp_server/` | Opt-in stdio MCP shim invoked as `brainpalace mcp`. Thin wrapper over `DocServeClient` + `discovery.py` exposing 5 read-only tools (`query`, `status`, `whoami`, `folders_list`, `jobs_list`) to MCP-aware AI clients. Tests at `brainpalace-cli/tests/mcp_server/`. **Named `mcp_server`, not `mcp`** — the original `mcp` name collided with the SDK's top-level `mcp` package under `coverage --cov=brainpalace_cli` instrumentation, so renaming the sub-package was the surgical fix. CLI subcommand `mcp` (user-facing) is unchanged. |

---

## Quick Start for Developers

### Prerequisites
- **Python 3.10+**
- **Poetry** - `pip install poetry`
- **Task** - `brew install go-task/tap/go-task`
- **OpenAI & Anthropic API keys**

### Installation
```bash
git clone git@github.com:bxw91/brainpalace.git
cd brainpalace
task install
```

### Global CLI Setup (Recommended)
```bash
task install:global
```
This installs `brainpalace-serve` and `brainpalace` in your current Python environment's bin folder, allowing you to run them from any directory.

---

## Task Commands

The root `Taskfile.yml` orchestrates the entire monorepo.

| Command | Description |
|---------|-------------|
| `task install` | Install all dependencies |
| `task install:global` | Install tools as global CLI commands |
| `task dev` | Start server in development mode |
| `task pr-qa-gate` | **MANDATORY** before push: Run all quality checks |
| `task test` | Run all tests |
| `task eval` | Run the retrieval eval harness (directional, **not** a gate) |
| `task status` | Wrapper for `brainpalace status` |

---

## Testing

### Running the QA Gate
Before pushing any changes, you MUST run:
```bash
task pr-qa-gate
```
This ensures:
1. Linting (Ruff) passes.
2. Type checking (mypy) passes.
3. Unit and Integration tests pass.
4. Test coverage is above 50%.

> **The local gate is necessary, not sufficient.** CI (and the release publish
> workflow) re-run the suite in a *pristine env with no Claude Code plugin
> installed* and may resolve a different Click version. A test that passes
> locally can still fail there — see "Interactive CLI tests must be
> host-independent" below.

### Interactive CLI tests must be host-independent
Tests that drive `brainpalace init` / `config wizard` with a canned stdin string
(`CliRunner(..., input=...)`) are a recurring source of pass-locally/fail-CI
breaks. Two host-dependent behaviors bite:

- **Claude Code plugin presence.** `claude_plugin_installed()` changes the
  wizard/init wording and which prompts appear. A dev box running inside Claude
  Code reports the plugin present; CI does not. **Mock it** (e.g.
  `patch("brainpalace_cli.commands.config.claude_plugin_installed",
  return_value=False)`) so the prompt sequence is fixed.
- **Exhausted-stdin behavior.** When the input runs out, some Click versions
  return each prompt's *default* (so the wizard completes) while others **abort**
  (`SystemExit`). Never rely on this. **Answer every prompt explicitly** — count
  the prompts in the command and supply one line each, including any sub-prompts
  and the final `Proceed?`/continue gate. When you add a prompt, realign *all*
  interactive tests' stdin in the same change.

Also mock the network port scan (`_find_available_api_port`) so the wizard
doesn't probe real sockets under test. A test that follows these rules behaves
the same on every host and in CI.

### Documentation Freshness (`last_validated`)
Audited docs carry a `last_validated: YYYY-MM-DD` frontmatter field. It means
**"this doc was last read against the live code and confirmed accurate on that
date"** — it is *not* an auto "last modified" stamp.

The rule:

> **When you change an audited doc's content, you must re-confirm it against the
> code and bump its `last_validated` to today.** A doc whose last git commit is
> newer than its `last_validated` is *stale* — the claim of validation no longer
> covers the current text.

Enforcement is automated. `task lint:doc-freshness` (run as part of
`task before-push`) fails if any audited doc was committed after its
`last_validated` date, or is missing the field. The audited set is the same
globs used by the audit scripts: `docs/*.md`,
`brainpalace-plugin/commands/*.md`, `brainpalace-plugin/skills/*/references/*.md`,
`brainpalace-plugin/agents/*.md`, plus `README.md`, `CLAUDE.md`, `AGENTS.md`.

To clear staleness after actually re-reading the docs:
```bash
python scripts/check_doc_freshness.py        # list what's stale
python scripts/add_audit_metadata.py         # stamp today's date into frontmatter
```
Do **not** run `add_audit_metadata.py` to silence the check without re-reading
the doc — the date asserts a human (or you) verified it against the code.

### Changelog style (`docs/CHANGELOG.md`)
Changelog entries are for **readers deciding whether a change affects them**, not
for explaining how it was built. Keep each entry **short**:

> **Each entry is ≤ 3 sentences.** A bold lead naming what changed, one sentence
> of user-facing impact, and at most one clause for the key default/gotcha or the
> cross-surface parity pointer. Reference the issue/PR (`(#NN)`) and let the
> **commit message** carry the root-cause / file-level detail — don't duplicate it
> here.

The cap applies to **every** entry, old and new — released sections may be
normalized for length in a deliberate pass, but never drop a real entry, version
header, date, or issue reference when tightening. Group entries under the standard
Keep-a-Changelog headings (`Added`, `Changed`, `Fixed`, `Docs`, …) within each
`[YY.M.N]` section.

Enforcement is automated. `task lint:changelog` (run as part of `task
before-push`) fails when any entry in the **`[Unreleased]`** section or the
**most recent released** section exceeds the 3-sentence cap; older sections are
out of scope (normalize them deliberately, never fail the build retroactively).
The check (`scripts/check_changelog_style.py`) strips inline code, link targets,
and CalVer dots before counting, so only real sentence terminators count.

### Test Directories
- `brainpalace-server/tests/`: Server-specific tests.
- `brainpalace-cli/tests/`: CLI-specific tests.
- `e2e/`: Full workflow integration tests.

### End-to-End Validation Script

Before releasing any version or merging major features, you MUST run the end-to-end validation script:

```bash
./scripts/quick_start_guide.sh
```

This script validates the complete BrainPalace workflow by:
1. Starting a real server instance
2. Indexing the project codebase (code included by default)
3. Running semantic, BM25, and hybrid search queries
4. Testing summarization features
5. Verifying proper error handling and cleanup

**Requirements:**
- `OPENAI_API_KEY` environment variable set
- Poetry and lsof installed
- Server and CLI dependencies installed

**Exit Codes:**
- `0`: All tests passed
- Non-zero: Test failures or setup issues

The script serves as both a release validation tool and a comprehensive demonstration of BrainPalace's capabilities.

### Retrieval Evaluation Harness

When you change anything that affects **retrieval quality** (indexing, chunking,
embeddings, fusion, reranking, graph), measure it instead of guessing:

```bash
task eval                 # recall@k + MRR per mode, diffed vs a committed baseline
```

This is **directional, not pass/fail**, and deliberately **not** part of
`pr-qa-gate` (scores are noisy and provider-dependent). It builds a throwaway
index over a small committed corpus, runs a query set, and flags any metric or
case that regressed against `tests/eval/baseline.json`. Needs `OPENAI_API_KEY`.
Full guide: [EVALUATION.md](EVALUATION.md).

---

## Troubleshooting

### ModuleNotFoundError: No module named 'src'
This usually means you are running the tool without installing it or the `PYTHONPATH` is not set.
**Solution**: Run `task install:global` or always use `poetry run`.

### Port 8000 Already in Use
**Solution**: `lsof -ti :8000 | xargs kill -9`

### Duplicated Results in Query
**Solution**: The system uses stable IDs based on file path and chunk index. If you see duplicates, run `brainpalace reset --yes` to clear the old index and re-index.

---

## Multi-Instance Architecture

BrainPalace supports running multiple concurrent instances with per-project isolation. This enables developers to work on multiple projects simultaneously without port conflicts or index cross-contamination.

### State Directory Structure

Each project stores its state in `.brainpalace/`:

```
<project-root>/
└── .brainpalace/
    ├── config.json      # Project configuration (optional, can be committed)
    ├── runtime.json     # Runtime state (DO NOT commit - add to .gitignore)
    ├── doc-serve.lock   # Lock file for preventing double-start
    ├── doc-serve.pid    # Process ID file
    ├── data/            # ChromaDB and index data
    └── logs/            # Server logs
```

### Runtime State Format

The `runtime.json` file contains:

```json
{
  "mode": "project",
  "port": 49321,
  "base_url": "http://127.0.0.1:49321",
  "pid": 12345,
  "instance_id": "abc123def456",
  "project_id": "my-project",
  "started_at": "2026-01-27T10:30:00Z"
}
```

### Lock File Protocol

The lock file prevents concurrent startup:

1. Server attempts exclusive lock on `doc-serve.lock`
2. If lock fails, another instance is starting/running
3. Lock released on graceful shutdown
4. Stale locks detected via PID validation

### Project Root Resolution

Project root is determined in this order:

1. **Git repository root**: `git rev-parse --show-toplevel`
2. **Marker files**: Directory containing `.brainpalace/`, `pyproject.toml`, `package.json`, `Cargo.toml`, etc.
3. **Current directory**: Fallback if no markers found

Symlinks are resolved to canonical paths to ensure consistent state directories.

### Configuration Precedence

Settings are resolved in order (first wins):

1. Command-line flags (`--port 8080`)
2. Environment variables (`DOC_SERVE_STATE_DIR`, `DOC_SERVE_MODE`, kill-switches)
3. Project config (`.brainpalace/config.yaml`)
4. Global config (`~/.config/brainpalace/config.yaml`, XDG)
5. Built-in (pydantic) defaults

**`config.yaml` is resolved per key as `code < global < project`** (env on top).
The server merges the global XDG `config.yaml` *under* the project file
(`provider_config.load_merged_config_dict` / `load_raw_config`): a key the project
omits is inherited from global, then the code default. Every block loader
(provider, git, session, indexing, bm25, query-log) reads this merged dict.

The project `config.yaml` is therefore **sparse** — it stores only values that
diverge from the inherited one:

- `brainpalace init` writes only explicit flags / divergent interactive answers;
  prompts default to the global value and accepting it writes nothing (inherits).
  With **no** global config, init seeds env-detected code defaults so the project
  stands alone.
- `brainpalace config unset <dotpath>` (and the dashboard's per-field **unset**
  control) removes a project override so the key inherits again. The dashboard
  shows a provenance badge (project/global/code) and, for project-set keys, the
  value it would fall back to if unset (`ConfigService.effective().inherited`).

Do **not** reintroduce verbatim "copy the global into the project" writes — that
breaks inheritance (a later global edit would no longer propagate).

> `config.json` (server `bind_host`/ports, runtime-managed) is **not** layered;
> only `config.yaml` participates in `code < global < project` resolution.

### Health Endpoint Enhancement

The `/health` endpoint now includes mode information:

```json
{
  "status": "healthy",
  "mode": "project",
  "instance_id": "abc123def456",
  "project_id": "my-project"
}
```

---

## Setup-surface parity (CLI · plugin · MCP)

BrainPalace exposes the **same install / configuration / setup behavior through
three independent front-ends**. They are separate code and docs, and they drift
apart silently — a change to one is **not** picked up by the others.

| Surface | Where it lives |
|---------|----------------|
| **CLI / bash** | `scripts/setup.sh` (guided), `scripts/install.sh`, and the `brainpalace init` / `config wizard` commands under `brainpalace-cli/` |
| **Claude plugin** | `brainpalace-plugin/commands/brainpalace-{setup,config,install,install-agent}.md`, `brainpalace-plugin/agents/setup-assistant.md`, `brainpalace-plugin/skills/configuring-brainpalace/**` |
| **MCP** | the `brainpalace mcp` entrypoint, the MCP client-config templates (duplicated in `scripts/setup.sh` and the plugin setup command), and `docs/MCP_SETUP.md` |

**Rule:** when you change install / configuration / setup behavior in **one**
surface, update the other two **in the same change** and record it in
`docs/CHANGELOG.md`. Behavior that must stay aligned includes: the config-file
location written (canonical = XDG `~/.config/brainpalace/config.yaml`), the
provider/wizard flow, whether project init is optional, the MCP client
templates, and the documented config search order.

**Parity checklist** — run through it for any setup-feature change:

- [ ] **CLI:** `scripts/setup.sh` + `scripts/install.sh` reflect the change.
- [ ] **Plugin:** `/brainpalace-setup`, `/brainpalace-config`, the
      `setup-assistant` agent, and the `configuring-brainpalace` references
      reflect it; bump each edited doc's `last_validated`.
- [ ] **MCP:** client templates + `docs/MCP_SETUP.md` reflect it.
- [ ] Config search order / write target matches the server resolver
      (`brainpalace-server/brainpalace_server/config/provider_config.py`) across
      every doc that lists it (XDG preferred, legacy `~/.brainpalace/` deprecated).
- [ ] `docs/CHANGELOG.md` `[Unreleased]` notes the change.

> **Why this section exists:** the CLI went global-first (XDG) while the plugin
> kept writing the deprecated `~/.brainpalace/` path, so the plugin's config was
> silently ignored whenever both were installed. This rule prevents a repeat.

---

## Dashboard parity — surface every feature

The control-plane dashboard (`brainpalace-dashboard/`) is meant to surface
**every** config option, CLI command, and project-server endpoint. Without
enforcement these drift: a new endpoint or command ships and the dashboard
never grows a control for it. The parity gate prevents that.

**The gate:** `tests/test_dashboard_parity.py`, run via
`task lint:dashboard-parity` (included in `task before-push`). It imports the
**live** sources of truth — not snapshots — and diffs them against the
checked-in coverage maps:

| Check | Live source | Allowlist (with reasons) | What "satisfied" means |
|-------|-------------|--------------------------|------------------------|
| **Config** | `brainpalace_cli.config_schema.*_KNOWN_FIELDS` | `ui_schema.DASHBOARD_HIDDEN_FIELDS` | Every schema leaf dotpath is rendered by `ui_schema.build_ui_schema()` **or** hidden with a reason. Config fields auto-render, so usually nothing to do. |
| **CLI** | `brainpalace_cli.cli.cli.commands` (Click group) | `coverage_maps.CLI_DASHBOARD_COVERAGE` | Every registered command maps to a dashboard tab/action **or** a `cli_only: <reason>` entry; no map entry for a removed command. |
| **Endpoint** | `brainpalace_server.api.main.app.routes` (dashboard route prefixes) | `coverage_maps.ENDPOINT_SURFACES` | Every live `route.path` maps to a tab **or** an `unsurfaced: <reason>` entry; no map entry for a removed route. Keys match the exact FastAPI `route.path` (`{param}` form; data ops are nested under `/index/`). |

**The coverage maps** live in
`brainpalace-dashboard/brainpalace_dashboard/coverage_maps.py`
(`CLI_DASHBOARD_COVERAGE`, `ENDPOINT_SURFACES`, plus a re-export of
`DASHBOARD_HIDDEN_FIELDS`). They are the only checked-in snapshots; every entry
that is not surfaced in the UI carries a one-line reason.

**To satisfy the gate when you add something:**

- [ ] **New config field** → it auto-renders. Only touch `ui_schema.py` to add a
      presentation `OVERRIDE`, or `DASHBOARD_HIDDEN_FIELDS` (with a reason) if it
      must not be shown.
- [ ] **New CLI command** → add a `CLI_DASHBOARD_COVERAGE` entry: the tab/action
      it maps to, or `cli_only: <reason>`.
- [ ] **New / changed server endpoint** → add the exact live `route.path` to
      `ENDPOINT_SURFACES`: the tab it maps to, or `unsurfaced: <reason>`. Remove
      any map key for a route you deleted/renamed.
- [ ] Build the dashboard control for anything user-facing, in the same change.
- [ ] `docs/CHANGELOG.md` `[Unreleased]` notes it.
- [ ] `task lint:dashboard-parity` green.

> **Why this section exists:** the dashboard's whole point is to be the single
> management surface; an un-enforced "remember to add it to the UI" rule rots
> immediately. The gate makes drift a failing test, not a silent gap.

---

## Code Ingestion & Language Support

BrainPalace supports AST-aware code chunking for 9+ programming languages using tree-sitter. The current implementation includes: **Python, TypeScript, JavaScript, Java, Go, Rust, C, C++, C#**.

Adding support for new programming languages is straightforward:

### Recommended Package: tree-sitter-language-pack

Use [`tree-sitter-language-pack`](https://pypi.org/project/tree-sitter-language-pack/) - a maintained fork with 160+ pre-built language grammars.

**Advantages:**
- Pre-compiled binaries (no C compiler needed)
- 160+ languages in a single dependency
- Permissive licensing (no GPL dependencies)
- Aligned with tree-sitter 0.25.x

**Installation:**
```bash
pip install tree-sitter-language-pack
```

### Simple API

```python
from tree_sitter_language_pack import get_language, get_parser

# Get parser for any supported language
parser = get_parser('rust')
language = get_language('rust')

# Parse code
tree = parser.parse(b"fn main() { println!(\"Hello\"); }")
```

### Step-by-Step: Adding a New Language

**Step 1: Verify language support**
```python
from tree_sitter_language_pack import get_language

try:
    lang = get_language('ruby')
    print("Ruby is supported!")
except Exception:
    print("Ruby not available")
```

**Step 2: Update extension mapping**

In `brainpalace_server/indexing/document_loader.py`:

```python
# Add to CODE_EXTENSIONS
CODE_EXTENSIONS: set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".rb",  # NEW: Ruby
}

# Add to EXTENSION_TO_LANGUAGE
EXTENSION_TO_LANGUAGE = {
    # ... existing mappings ...
    ".rb": "ruby",
}
```

**Step 3: Register with CodeChunker**

In `brainpalace_server/indexing/code_chunker.py`:

```python
class CodeChunker:
    SUPPORTED_LANGUAGES = [
        "python", "typescript", "javascript",
        "ruby",  # NEW
    ]
```

**Step 4: Add language-specific config (optional)**

```python
LANGUAGE_CHUNK_CONFIG = {
    "python": {"chunk_lines": 50, "overlap": 20},
    "ruby": {"chunk_lines": 50, "overlap": 20},  # NEW
    "java": {"chunk_lines": 80, "overlap": 30},  # Verbose
    "c": {"chunk_lines": 40, "overlap": 15},
}
```

### C# Language Support

C# is fully supported with AST-aware parsing:

**File Extensions:**
- `.cs` - C# source files
- `.csx` - C# script files

**Extracted Symbols:**
- Classes, interfaces, structs, records, enums
- Methods, properties, fields
- Parameters and return types
- Namespaces

**XML Documentation:**
BrainPalace extracts XML doc comments (`/// <summary>`, `/// <param>`, `/// <returns>`) and stores them as metadata on chunks.

**Tree-sitter Grammar:**
Uses the `c_sharp` grammar from `tree-sitter-language-pack`.

**Content Detection Patterns:**
- `using System;`
- `namespace` declarations
- Property accessors `{ get; set; }`
- Attributes `[AttributeName]`

### Available Languages (160+)

| Category | Languages |
|----------|-----------|
| Systems | C, C++, Rust, Go, Zig |
| JVM | Java, Kotlin, Scala, Groovy |
| .NET | C#, F# |
| Scripting | Python, Ruby, Perl, Lua, PHP |
| Web | JavaScript, TypeScript, HTML, CSS |
| Functional | Haskell, OCaml, Elixir, Erlang, Clojure |
| Data | SQL, JSON, YAML, TOML, XML |
| Config | Dockerfile, Terraform (HCL), Nix |
| Shell | Bash, Fish, PowerShell |
| Scientific | R, Julia, Fortran |
| Mobile | Swift, Objective-C |

### Alternative: Individual Packages

For minimal dependencies, use individual tree-sitter packages:

```bash
pip install tree-sitter-python tree-sitter-javascript
```

```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)
```

### Alternative: tree-sitter-languages

The original [`tree-sitter-languages`](https://pypi.org/project/tree-sitter-languages/) package (40+ languages):

```bash
pip install tree-sitter-languages
```

```python
from tree_sitter_languages import get_language, get_parser

language = get_language('python')
parser = get_parser('python')
```

### References

- [tree-sitter-language-pack on PyPI](https://pypi.org/project/tree-sitter-language-pack/)
- [tree-sitter-languages on PyPI](https://pypi.org/project/tree-sitter-languages/)
- [tree-sitter-languages GitHub](https://github.com/grantjenks/py-tree-sitter-languages)
- [Tree-sitter Documentation](https://tree-sitter.github.io)

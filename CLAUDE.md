# BrainPalace — repo guide for Claude

RAG system for AI coding assistants (BM25 + semantic vector + GraphRAG), per-project
servers with auto-discovery. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Monorepo layout

| Path | Role |
|------|------|
| [brainpalace-server/](brainpalace-server/) | FastAPI server: indexing, retrieval, providers, storage. Own `pyproject.toml` (Poetry). |
| [brainpalace-cli/](brainpalace-cli/) | `brainpalace` CLI: init/start/stop/index/query/status, server lifecycle, MCP. Own `pyproject.toml` (Poetry). Bundles the server at runtime. |
| [brainpalace-plugin/](brainpalace-plugin/) | Claude Code plugin (skills, commands, hooks). |
| [docs/](docs/), [e2e/](e2e/), [e2e-cli/](e2e-cli/), [integration/](integration/) | Docs, end-to-end and integration tests. |

Root is an organizational container + `Taskfile.yml` task runner. Each subpackage builds/tests independently.

## Build / test

`task` (Taskfile.yml) is the entry point. `task --list` shows all.

```bash
task install        # install server + cli (Poetry envs)
task test           # full suite — server + cli   (or: task test:server / task test:cli)
task check          # lint + typecheck, no tests
task before-push    # MANDATORY full quality gate before any push/merge
```

**Gotcha — headless env:** Poetry install fails with a `SecretServiceNotAvailableException` /
DBus keyring error when no desktop keyring is present. Disable the keyring backend:

```bash
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
task install
```

## Branching & releasing

- `task before-push` must pass before any push/merge.
- **Never push the local `stable` branch.** It is local-only by design. The branch model and
  the full release procedure live in **[docs/RELEASING.md](docs/RELEASING.md)** — follow it
  exactly. Creating a GitHub Release is what publishes to PyPI (OIDC; never `poetry publish`
  by hand).

## Codebase search — dogfood BrainPalace

This repo is indexed by its own tool. **Use `brainpalace query` for codebase search here**, not
Grep/Glob/find:

```bash
brainpalace status                                   # server health, chunk count
brainpalace query "your question" --mode hybrid --top-k 8
```

Server auto-discovers config by walking up to `.brainpalace/`. If the server is down, start it:
`brainpalace start`. Provider config lives in the gitignored `.brainpalace/config.yaml`; the
`init` defaults are OpenAI embeddings + Anthropic summarization, so set whichever API keys your
config uses (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`). Change providers with `brainpalace config`.

Modes: `bm25` (exact terms), `vector` (semantic/concepts), `hybrid` (default), `graph`
(dependencies/relationships), `multi` (fusion).

## Live watch, session memory, status

- **Live re-index:** `brainpalace index <path> --watch auto` (or `--watch off`) marks the
  folder watched; the server's `FileWatcherService` re-indexes on change. `--watch-debounce
  <seconds>` tunes the debounce. `folders add` defaults to `--watch auto`.
- **Session memory (ON by default for new projects):** `brainpalace init` writes
  `session_indexing.enabled: true` into `.brainpalace/config.yaml`; the server indexes this
  project's AI chat transcripts (assistant + tool turns). Opt out with `init --no-sessions`.
  Existing projects (no `session_indexing` block) stay off. Privacy model, embedding cost, and
  tuning: [docs/SESSION_INDEXING.md](docs/SESSION_INDEXING.md#embedding-cost--read-before-enabling).
- **`brainpalace status`** shows a per-feature view: document indexing, file watcher (with a
  clear "0 folders — none marked watch=auto" state), session memory (on/off, watching/idle,
  session-chunk + curated-memory counts), and graph index. `total_documents` is derived from
  the persisted folder manifests, so it's correct even when indexing ran in the job worker.
- **`init --start` pre-flight:** validates embedding + summarization providers (using the
  server's own rules) before launching, failing fast with the missing env var instead of
  crashing mid-index on a misconfigured provider.

## Local-only state

`.brainpalace/` is gitignored (per-project index data). `.planning/` is local planning scratch,
excluded via `.git/info/exclude` — never committed.

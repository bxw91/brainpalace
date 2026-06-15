---
last_validated: 2026-06-15
---

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

## Setup-surface parity — CLI · plugin · MCP (MANDATORY)

Install/config/setup behavior is exposed through **three independent front-ends**
that drift apart silently: **CLI** (`scripts/setup.sh`, `scripts/install.sh`,
`brainpalace init`/`config wizard`), **Claude plugin**
(`brainpalace-plugin/commands/brainpalace-{setup,config,install,install-agent}.md`,
`agents/setup-assistant.md`, `skills/configuring-brainpalace/**`), and **MCP**
(`brainpalace mcp`, the client-config templates, `docs/MCP_SETUP.md`).

**When you change setup/install/config behavior in one surface, update the other
two in the same change + note it in `docs/CHANGELOG.md`.** Canonical config path
is XDG `~/.config/brainpalace/config.yaml` (legacy `~/.brainpalace/` is
deprecated). Full rule + parity checklist:
[docs/DEVELOPERS_GUIDE.md → Setup-surface parity](docs/DEVELOPERS_GUIDE.md#setup-surface-parity-cli--plugin--mcp).

**Config resolves `code < global < project`** (env overrides on top). The server
merges the global XDG `config.yaml` under the project `.brainpalace/config.yaml`
per key (`provider_config.load_merged_config_dict` / `load_raw_config`); a key the
project omits is inherited from global, then the code default. The project file is
**sparse** — `init` writes only values that diverge from the inherited one, and
`brainpalace config unset <dotpath>` (or the dashboard's per-field unset) removes
a project override so the key inherits again. Don't reintroduce verbatim
"copy the global into the project" writes.

## Dashboard parity — surface every feature (MANDATORY)

When you add a **config option**, **CLI command**, **server endpoint**, or any
**user-facing datum**, you MUST surface it in the control-plane dashboard in the
same change — or add it to the relevant allowlist with a one-line reason. Config
fields auto-render from `config_schema` (hide one only via
`ui_schema.DASHBOARD_HIDDEN_FIELDS` with a reason); CLI commands and server
endpoints are checked against the checked-in maps in
`brainpalace-dashboard/brainpalace_dashboard/coverage_maps.py`
(`CLI_DASHBOARD_COVERAGE` / `ENDPOINT_SURFACES` — every non-surfaced entry needs
a `cli_only:`/`unsurfaced:` reason). The gate `lint:dashboard-parity` (in
`task before-push`) imports the LIVE config schema, the LIVE Click group, and the
LIVE FastAPI app and fails on any unclassified addition or stale map entry. Note
the change in `docs/CHANGELOG.md`. Full rule + how to satisfy each check:
[docs/DEVELOPERS_GUIDE.md → Dashboard parity](docs/DEVELOPERS_GUIDE.md#dashboard-parity-surface-every-feature).

## AI-guidance parity — single source (MANDATORY)

AI-facing usage guidance (search rules, modes, `--json` contract, server-down
behavior) reaches three surfaces — the **Claude plugin skill**
(`brainpalace-plugin/skills/using-brainpalace/SKILL.md`), the **MCP server**
(`Server(instructions=...)` + the `ai_guide` tool), and the **SessionStart hook**
— from **one source**: `brainpalace-cli/brainpalace_cli/data/ai_guidance.md`.
Three nested tiers slice from it: **NUDGE ⊂ CORE ⊂ FULL** (hook gets NUDGE, MCP
instructions get CORE, skill + `ai-guide --tier full` + the `ai_guide` MCP tool
get FULL). The loader is `brainpalace_cli/ai_guidance.py`; `brainpalace ai-guide`
renders it.

**Edit guidance in `ai_guidance.md` ONLY.** `SKILL.md` is a GENERATED artifact —
never hand-edit it; regenerate with
`cd brainpalace-cli && poetry run brainpalace ai-guide --format skill > ../brainpalace-plugin/skills/using-brainpalace/SKILL.md`.
The hooks are thin shims (`brainpalace hook sessionstart`); all logic lives in the
CLI, so a CLI upgrade propagates changes (legacy fat hooks auto-migrate on
`brainpalace start`). Rules: verify contract claims against LIVE code (never
doc-vs-doc); AI guidance + user-facing CLI strings are **English-only**; never put
literal tier-marker tokens in the source's header comment. The gate
`lint:ai-guidance-parity` (in `task before-push`) fails on SKILL.md drift, empty
tier slices, hook-shim drift, or non-English letters. Note the change in
`docs/CHANGELOG.md`. Full rule:
[docs/DEVELOPERS_GUIDE.md → AI-guidance parity](docs/DEVELOPERS_GUIDE.md#ai-guidance-parity-single-source).

**Interface doc-sync — `sync-docs`.** Interface docs (command docs, query modes,
skills, config keys, MCP tools, endpoints) are deterministically gated against
LIVE code by `scripts/check_doc_sync.py` (`lint:doc-sync`); the generator owns the
machine regions and the CLI never calls an LLM. `sync-docs --check` also asserts
the dump/checker `schema_version` and wraps the ai-guidance + dashboard parity
gates as one entry point. The residual **human prose** is authored in-session via
the `authoring-brainpalace-docs` skill; editing an interface-source file fires a
PostToolUse soft-nudge (`brainpalace hook posttooluse`, thin shim) to run
`sync-docs --fix`. The nudge never blocks.

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

## Docs — `last_validated` freshness

Audited docs carry `last_validated: YYYY-MM-DD` in frontmatter (human "confirmed
accurate on this date", display only). The gate compares a hash of authored
content recorded in the sidecar manifest `scripts/doc_freshness.json` (kept out
of frontmatter so docs render clean on GitHub). **Edit a doc's content → re-check
vs code → re-stamp** (`python scripts/add_audit_metadata.py`). `task before-push`
runs `lint:doc-freshness` (fails when a doc's authored content no longer matches
its manifest hash). The hash catches same-day edits a date comparison would miss.
Rule:
[docs/DEVELOPERS_GUIDE.md](docs/DEVELOPERS_GUIDE.md#documentation-freshness-last_validated);
release-time step: [docs/RELEASING.md](docs/RELEASING.md).

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
- **Sessions = two independent capabilities** (see
  [docs/SESSION_INDEXING.md](docs/SESSION_INDEXING.md)): **archive** (copy raw transcripts to
  `.brainpalace/`, free, durable backup) and **index** (embed them, billable). Gated by the
  presence of each config/flag; `retain_days <= 0` = forever. **Absent `session_indexing` block
  (existing projects): archive ON, index OFF** — back up transcripts without surprise embedding
  cost. `brainpalace init` writes both ON; `--no-sessions` / `--no-archive` disable each
  independently. Kill-switches: `SESSION_INDEXING_ENABLED=false`, `SESSION_ARCHIVE_ENABLED=false`.
  Archive folders are tool-tagged `YYYY-MM-DD-<tool>` (today `claude-code`). ⚠️ The raw archive
  holds **full transcripts incl. user turns/secrets**.
- **`brainpalace status`** shows a per-feature view: document indexing, file watcher (with a
  clear "0 folders — none marked watch=auto" state), session archive (on/off, files, size),
  session memory/index (on/off, watching/idle, session-chunk + curated-memory counts), and graph
  index. `total_documents` is derived from the persisted folder manifests, so it's correct even
  when indexing ran in the job worker.
- **`init --start` pre-flight:** validates embedding + summarization providers (using the
  server's own rules) before launching, failing fast with the missing env var instead of
  crashing mid-index on a misconfigured provider.

## Local-only state

`.brainpalace/` is gitignored (per-project index data). `.planning/` is local planning scratch,
excluded via `.git/info/exclude` — never committed.

---
last_validated: 2026-06-02
---

# Changelog

All notable changes to BrainPalace are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning is **CalVer** `YY.M.N` — 2-digit year · month · Nth release that
month (the counter resets monthly). It looks like SemVer but is not.

---

## [26.6.12] - 2026-06-02

### Changed
- **Plugin `/brainpalace-setup` is now global-first.** It writes the provider
  config to the XDG global `~/.config/brainpalace/config.yaml` — the **same file
  the CLI and `brainpalace init` use** — instead of the deprecated legacy
  `~/.brainpalace/config.yaml`. Adds an optional MCP-client wiring step (user
  scope) and makes project init the optional last step. Config-location docs
  (`/brainpalace-config`, the setup-assistant agent, and the
  configuring-brainpalace references) were corrected to the XDG-canonical search
  order and the non-existent `brainpalace config set` examples removed.
- **README install order:** "Install as a CLI or MCP server" now appears above
  "Install as a Claude Code plugin", and its commands are each in their own
  copy-paste code block.
- **Guided `setup.sh` UX polish:** the detected provider API key is now shown as
  a green "✓ detected" tag next to the matching provider in the selection menu
  (instead of a separate line); the MCP-client step lists only auto-detected
  clients by default with an "other — show all" escape hatch; declining the
  optional project step no longer duplicates the next-steps text (shown once
  after Verify); the trailing "Docs:" list was removed from the summary.
- **`config wizard` prompts:** the summarization provider now defaults to the
  embedding provider when it can summarize (openai/ollama), else to whichever
  summarization API key is already set (else anthropic) — no longer hard-coded to
  anthropic; the GraphRAG and Deployment-mode questions render the choice prompt
  on its own line below the options, and the GraphRAG options were reworded to
  neutral trade-offs (no scare wording). Mirrored in the plugin setup wizard.
- **Guided setup prompts are spaced out:** a blank line now precedes every
  question (CLI `config wizard` prompts and `setup.sh`'s own `ask`/`confirm`
  prompts), so consecutive questions in a step are visually separated.

## [26.6.11] - 2026-06-02

### Changed
- Guided `setup.sh`: the "install from a local checkout" prompt now appears
  only when a source checkout is actually detected — network (`curl | bash`)
  users no longer see a dev-only question. Setup also warns up front that the
  first pipx install pulls a large RAG/ML stack and can take a few minutes.
- Guided `setup.sh`: when brainpalace is already installed, setup now fetches
  the latest version from PyPI and shows it alongside the installed one —
  "update available" (prompt defaults to yes) or "you're up to date" — instead
  of asking to reinstall with no idea whether a newer version exists.
- **Guided `setup.sh` is now global-first.** It installs brainpalace, configures
  the provider/API **globally** (`brainpalace config wizard --global` →
  `~/.config/brainpalace/config.yaml`), and wires MCP at user scope first.
  Setting up and indexing a project is now the **last, optional** step — declining
  prints a copy-paste `brainpalace init` example. New: `brainpalace config wizard
  --global` writes the global config that every project inherits. The mid-flow
  "Next steps" block printed by `install.sh` is suppressed during guided setup
  (the script gives simpler end-of-run guidance).

## [26.6.10] - 2026-06-02

### Added
- **`brainpalace init` is full setup by default.** A bare `init` now writes
  config, starts the server, indexes the project (`watch=auto`), archives
  transcripts, and embeds transcripts. Interactive runs show the resolved plan
  and confirm once (the two embedding steps are billable); declining falls back
  to config-only. New flags: `--yes` / `-y` (skip the prompt, apply the full
  plan — for scripts/CI), `--no-start`, and `--no-watch`, alongside the existing
  `--no-sessions` / `--no-archive`. Non-interactive / `--json` runs stay
  config-only unless `--yes` is passed, so existing automation is unaffected.

### Fixed
- **Uninstall no longer misreads a pipx/uv install as bare pip.**
  `detect_install_manager` classified the `~/.local/bin` shim path verbatim;
  pipx/uv install a *symlink* there with no `/pipx/` or `/uv/tools/` segment, so
  `brainpalace uninstall` printed a `pip uninstall` line that fails PEP 668
  (`externally-managed-environment`) on Debian/Ubuntu system Python — and
  `brainpalace update` ran the wrong upgrade. It now classifies the resolved
  symlink target and the shebang. The guided `scripts/uninstall.sh` also retries
  with `--break-system-packages` for genuine system-pip installs.
- **`init` start/watch work without a `brainpalace` binary on PATH.** The nested
  start and `folders add` steps spawned `["brainpalace", ...]`, which raised
  `FileNotFoundError` when the console script was not installed on PATH (running
  from source / as a module / uninstalled dev checkout). They now fall back to
  `python -m brainpalace_cli` with the current interpreter.

### Changed
- **`init` output distinguishes status from actions.** After the confirmation,
  init prints why it pauses (server cold-boot, not transcript work) and that
  indexing is enqueued in the background. The post-init summary now splits
  completed actions under `Done:` from genuine follow-ups under `Next steps:`.
- Docs (INSTALL.md, README, USER_GUIDE) updated for the new `init` default and
  the `--no-*` / `--yes` opt-outs. Internal: the MCP none-arguments handshake
  test is now environment-independent (no longer assumes no server is running).

## [26.6.9] - 2026-06-02

### Fixed
- **`init` no longer hardcodes the Anthropic summarizer.** The default
  `config.yaml` now picks providers from the API keys present in the
  environment: summarization prefers `anthropic` → `openai` → `gemini` →
  `grok`, embedding prefers `openai` → `cohere`, each falling through to the
  next whose key is set. An OpenAI-only environment gets a working config with
  no edit — previously `init --start` failed the provider preflight on the
  missing `ANTHROPIC_API_KEY` and left the user editing config on a fresh
  project. The user's global XDG `config.yaml` still wins when present.
- **`brainpalace start` / `stop` now resolve the project root correctly in a
  mono-repo.** Both commands carried byte-identical resolvers that tried the
  git top-level *first*, so a sub-project whose only `.git` lives at the
  workspace root resolved to the workspace root and reported "Project not
  initialized" — even with a local `.brainpalace/`. They now import the
  canonical `config.resolve_project_root`, which checks the nearest
  `.brainpalace/` before git (matching `whoami`/`doctor`/`index`/`query`/
  `status`).
- **`test_reset_index_success` is no longer order-dependent.** The reset route
  gates on `app.state.job_service` queue stats and calls
  `app.state.indexing_service.reset()`; the test patched an unrelated
  `get_indexing_service` symbol, so leaked job state from a prior test could
  flip it to a 409. The reset tests now override the symbols the route actually
  reads, and the conflict test forces the 409 path authoritatively.

## [26.6.8] - 2026-06-02

### Added
- **`brainpalace update`** — one-command upgrade. Auto-detects how the CLI was
  installed (pipx / uv / pip) and runs the matching upgrade, then reminds you to
  restart the server. `--yes` skips the confirm.
- **`brainpalace uninstall` is now a guided teardown** when run with no flags:
  confirms each step (stop servers, remove plugin dirs across runtimes/scopes,
  surgically strip the `brainpalace` entry from MCP client configs while keeping
  your other servers, delete selected per-project state, delete global state),
  then prints the leftover manual steps. For pipx/uv it offers to run the
  package uninstall as its final act; for pip it prints the command (a process
  can't delete its own running env). The shell-rc API key is always left to you.
  `--yes` / `--json` keep the previous non-interactive behaviour (global data +
  server stop only).

## [26.6.7] - 2026-06-02

### Added
- **Guided uninstall — `scripts/uninstall.sh`.** Interactive teardown mirroring
  `setup.sh`: stops servers, removes plugin dirs (all runtimes, both scopes),
  surgically strips the `brainpalace` entry from MCP client configs (keeping
  your other servers), uninstalls the package (auto-detected pipx/uv/pip), then
  offers multi-select per-project and global-state deletion. Shell rc is left
  to the user (an exported API key may be shared with other tools).
- **"Full uninstall (teardown)" docs** in `docs/INSTALL.md` and both skill
  installation guides, with a guided-uninstall curl one-liner.

### Fixed
- **Broken install URLs pointing at the local-only `stable` branch.** The
  README `setup.sh` one-liner and the `PLUGIN_GUIDE.md` CI `pip install`
  examples fetched `…/stable/…` / `@stable`, which 404 on GitHub (only `main`
  is published). Now `main`.
- **Documented a CLI command that does not exist.** `brainpalace uninstall
  --agent <runtime>` was referenced across the docs, but `uninstall` removes
  global data (no `--agent`) and `install-agent` only installs — there is no
  CLI to remove a plugin. Replaced with direct `rm -rf` of the plugin dirs.
  Also fixed `install-agent --scope global` → `--global` (wrong flag).

## [26.6.6] - 2026-06-02

### Changed
- **Session archiving is now independent of indexing and always-on by default.**
  Archive (copy raw transcripts into `.brainpalace/`, free) and index (embed
  them, billable) are two separate capabilities, each gated by the presence of
  its config/flag. **Existing projects with no `session_indexing` block now
  archive ON / index OFF** — transcripts are backed up (Claude Code prunes
  originals after ~30 days) without any surprise embedding cost. `brainpalace
  init` writes both ON; `--no-sessions` and `--no-archive` disable each
  independently. New kill-switch `SESSION_ARCHIVE_ENABLED=false` (alongside the
  existing `SESSION_INDEXING_ENABLED=false`).
- **`retain_days <= 0` now means keep forever** (no age cutoff) for both index
  and the new independent `archive.retain_days`. Defaults are `0` (forever).
  Previously `0` would have skipped everything. ⚠️ First-run forever-indexing of
  a large transcript history can be a big embedding bill (no 90-day cap now);
  set a positive `retain_days` to cap it.
- **Tool-tagged archive folders.** Archive date folders are now
  `YYYY-MM-DD-<tool>` (e.g. `2026-06-01-claude-code`) so same-day sessions from
  different tools sort adjacently and future multi-tool support slots in
  cleanly. Manifest entries gain a structured `tool` field (the source of
  truth — consumers must not parse paths). No migration: existing local archives
  may be wiped (rebuildable from `~/.claude` within its 30-day window).
- **`brainpalace status`** now shows session **archive** and **index** on
  separate rows, covering all four on/off states.

### Fixed
- **Doc-freshness gate no longer false-positives on frontmatter-introduction.**
  `scripts/check_doc_freshness.py` treated the commit that *adds* a doc's
  `last_validated` frontmatter block as a content change (it only ignored the
  `last_validated:` line, not the surrounding `---` fences / blank line), so
  five correctly-stamped docs were wrongly flagged stale. Frontmatter fence and
  blank lines are now recognised as metadata too.

## [26.6.5] - 2026-06-02

### Fixed
- **Server no longer fails to start when the summarization provider's API key is
  absent.** `EmbeddingGenerator` built the summarization provider in its
  constructor, so a missing key (e.g. the shipped default
  `summarization: anthropic` on a machine that only has `OPENAI_API_KEY`) raised
  `AuthenticationError` during startup and the whole server failed to boot —
  even though embeddings, document indexing, and session memory only need the
  embedding provider. The summarization provider is now built lazily on first
  summary; code-summary generation already degrades to docstring extraction on
  error, so a missing summarization key falls back gracefully instead of
  crashing. (`brainpalace start` has no provider pre-flight, unlike
  `init --start`, so this previously surfaced as a raw traceback.)

## [26.6.4] - 2026-06-01

### Fixed
- **File watcher / reindex now prunes deleted files.** A pure delete left the
  chunk queryable and the document count stuck. Three coupled defects: the job
  verifier treated a net-negative chunk delta (eviction) as failure and marked
  the watcher job failed; the indexing pipeline's empty-docs early-return
  skipped the BM25 rebuild, so `delete_by_ids` (vector store only) left the
  chunk in BM25; and that path carried over the entire prior manifest including
  the deleted file. Eviction-only runs now pass verification, rebuild BM25 from
  the surviving chunks, and the manifest keeps only the unchanged entries.
- **`reset` and `folders remove` no longer leave stale manifests.** They
  cleared the chroma/bm25/graph stores but kept `.brainpalace/manifests/*.json`,
  so the next `folders add` / `index` saw every file as unchanged and indexed
  0 chunks into an empty store. `ManifestTracker.delete_all()` is now called on
  `reset`, and `remove_folder` deletes the folder's manifest.

### Changed
- **Session memory is ON by default for newly `init`-ed projects.**
  `brainpalace init` writes `session_indexing.enabled: true` by default
  (interactive runs confirm with a default of yes; non-interactive / `--json`
  runs enable it). Pass `brainpalace init --no-sessions` to opt out. The
  default applies only to a freshly written `config.yaml` — re-init over an
  existing config is left untouched. Projects with no `session_indexing` block
  (existing projects) stay off; this is not retroactive. Only assistant/tool
  turns are indexed; user turns remain separately opt-in.

### Internal
- Hardening: a zero-change indexing run whose store is empty but whose manifest
  claims indexed files now fails loudly instead of silently reporting done at
  0% (surfaces a stale-manifest desync for re-index with force).

## [26.6.3] - 2026-06-01

### Changed
- **Session live-watcher debounce default raised 2s → 30s**
  (`session_indexing.watch_debounce_ms`). AI transcripts are written
  per-message in bursts (quiet during generation, then a burst of lines), so
  the old 2s window fired redundant re-index passes mid-turn on an in-progress
  transcript. 30s batches a whole turn; freshness is low-value here (recall
  targets *past* sessions, not the live one). Tunable per project; the archive
  deletion watcher stays at 1s.

### Internal
- **CI: GitHub Actions Node 20 → Node 24.** Bumped `actions/checkout@v6`,
  `setup-python@v6`, `cache@v5`, `upload-artifact@v7`, `codecov-action@v5`, and
  set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` to carry the remaining Node 20
  actions (`arduino/setup-task`, codecov's internal `github-script`) onto
  Node 24 ahead of the 2026-06-16 default flip and 2026-09-16 removal.
- **Docs:** README usage examples (codebase / docs / graph / session memory),
  a Session Memory badge, and clarified that automatic session capture is
  Claude Code-transcript-specific (works from CLI or plugin install).

## [26.6.2] - 2026-06-01

Durable, user-curatable session archive: session indexing now reads from a
local archive copy instead of the live `~/.claude` transcripts.

### Added
- **Session archive.** On a transcript change the raw `.jsonl` is copied
  verbatim into `.brainpalace/session_archive/<YYYY-MM-DD>/`, and indexing runs
  off the archive copy. `~/.claude` is treated as read-only. Sessions survive
  Claude Code removal / auto-delete. Opt-out via `session_indexing.archive.enabled`.
- **Curation by deletion.** Deleting an archived transcript (or a dated folder)
  purges that session's index chunks and writes a tombstone, so the live source
  is never re-synced (no resurrection).
- **Provenance.** Chunks record `origin_path` (the live source) alongside
  `source_path` (the archive copy).
- **Status.** `brainpalace status` / `/status` report `archived_sessions`,
  `archived_files`, `archived_bytes`, and `tombstoned`.
- **`brainpalace reset --include-sessions`** also deletes the archive; a plain
  reset preserves it.

### Fixed
- Chunk purge used a flat multi-key ChromaDB `where` filter that ChromaDB
  rejects ("expected exactly one operator"); deletions never purged chunks.
  Wrapped in `$and`.
- Subagent transcripts carry the parent's `sessionId`, so a `session_id`-keyed
  manifest collided each parent with its subagents (undercount, broken mtime
  no-op, and a data-loss path where deleting one subagent purged the parent's
  chunks). Manifest is now keyed per file; a session is purged only when all of
  its files are gone.

## [26.6.1] - 2026-06-01

Second release: watcher/session-memory/status fixes plus first-run UX and
correctness fixes found during integration testing.

### Added

- **`index --watch` / `--watch-debounce`** — mark a folder live-watched (or
  `--watch off`); the server's `FileWatcherService` re-indexes on change with a
  tunable debounce.
- **`init --sessions` session memory** — opt-in, privacy-first indexing of this
  project's AI chat transcripts (assistant + tool turns). Default off; `init`
  prompts on a TTY, stays off non-interactively.
- **`status` per-feature view** — document indexing, file watcher (with a clear
  "0 folders — none marked watch=auto" state), session memory (on/off,
  watching/idle, session-chunk + curated-memory counts), and graph index.
- **`init --start` provider pre-flight** — validates embedding + summarization
  providers before launching, failing fast with the missing env var instead of
  crashing mid-index.

### Fixed

- **Session chunks upsert to Chroma** — the session chunker stored list
  (`role_mix`, `tools_used`, `files_touched`) and `None` metadata values that
  Chroma rejects ("Expected metadata value to be a str, int, float or bool"),
  crashing session indexing at boot on every project. Lists are now comma-joined
  and unset optional keys dropped.
- **`folders add` watch default** — bare `folders add .` now defaults to
  `--watch auto` (was `off`), matching the documented behaviour so the file
  watcher isn't left at "0 folders".
- **Summarization `api_key_env` ignored the provider** — an OpenAI-only user who
  set `summarization.provider: openai` but no `api_key_env` got
  "Set ANTHROPIC_API_KEY" and a startup crash. The conventional env var is now
  derived from the selected provider when unset (openai→`OPENAI_API_KEY`,
  cohere→`COHERE_API_KEY`, gemini→`GEMINI_API_KEY`, grok→`XAI_API_KEY`); error
  messages name the correct var.
- **`init --start` re-run** — re-running after a first run that aborted at the
  provider pre-flight now starts the server idempotently instead of hitting the
  already-initialized no-op.
- **`init --force`** — no longer overwrites a user-edited `.brainpalace/
  config.yaml` (provider/embedding/summarization/storage/graphrag settings are
  preserved; use `brainpalace config` to change providers).
- **`status` `total_documents`** — derived from persisted folder manifests, so
  it's correct even when indexing ran in the job worker. Folder `chunk_count` is
  cumulative.

### Docs

- Documented the session-memory embedding cost (50% sliding-window overlap at
  `window=4`/`stride=2`; `stride: 4` ~halves it) in `SESSION_INDEXING.md` and
  `CLAUDE.md`.

## [26.5.1] - 2026-05-30

First public release of BrainPalace.

### Highlights

- **Hybrid retrieval** — BM25 + vector + GraphRAG, fused (`hybrid`/`multi`) or
  selectable per call (`bm25`/`vector`/`graph`).
- **Session intelligence** — curated memory (`remember`/`recall`,
  markdown-truth) + session-start context injection; session indexing/extraction
  into searchable summaries, decisions, and a typed knowledge graph;
  cross-session linking that supersedes stale decisions and promotes durable
  ones into memory.
- **Persistent SQLite graph backend** with temporal validity (per-edge validity
  windows, `invalidate`, `timeline`).
- **Time-decay ranking**, **git-history indexing** (commit messages + diff
  stats), and an opt-in **LSP cross-reference** symbol graph.
- **AST-aware code chunking** (Python, TypeScript, JavaScript, Java, Kotlin, C,
  C++, C#, Go, Rust, Swift), optional **LLM code summaries**, opt-in
  **cross-encoder reranking**.
- **Multi-instance** (one server per project, auto port allocation +
  `.brainpalace/runtime.json` discovery), **file watcher**, **incremental
  indexing**, **embedding cache**.
- **Interfaces** — CLI (`brainpalace` / `bp`), opt-in **MCP server**, and a
  **Claude Code plugin** (30 slash commands, 3 agents, 2 skills).
- **Pluggable providers** — embeddings (OpenAI · Cohere · Ollama), summarisation
  (Anthropic · OpenAI · Gemini · Grok · Ollama); fully-local via Ollama.

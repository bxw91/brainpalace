---
last_validated: 2026-07-21
---

# Changelog

All notable changes to BrainPalace are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning is **CalVer** `YY.M.N` — 2-digit year · month · Nth release that
month (the counter resets monthly). It looks like SemVer but is not.

Entries are kept short (≤ 3 sentences and ≤ 320 characters); see
[DEVELOPERS_GUIDE.md → Changelog style](DEVELOPERS_GUIDE.md#changelog-style-docschangelogmd).

---

## [Unreleased]

_Entries accumulate here between releases. The release step renames this to
`## [YY.M.N] - DATE` and adds a fresh empty `## [Unreleased]` above it — never
hand-number an unreleased section._

## [26.7.9] - 2026-07-21

### Added
- **Unified multi-runtime setup via `setup.sh`.** The guided installer now offers
  a multi-select over Claude, Codex, OpenCode, Antigravity, and skill-runtime in
  one run; `/brainpalace-setup` mirrors the same wiring for setup-surface parity.
- **Antigravity (agy) runtime support.** `install-agent --agent antigravity`
  mirrors the Codex converter — skill-runtime flatten + `AGENTS.md`, no
  tool-name remap.
- **`install-mcp --client` writes MCP config for more editors.** Now supports
  Cursor, Windsurf, VS Code/Copilot, Kilo, Cline, Qwen, and Kimi in addition to
  Claude; `setup.sh`'s multi-select wires the five MCP-only editors (Qwen/Kimi
  wire alongside their skills converter in Phase C).
- **Qwen Code + Kimi CLI runtimes (skills + MCP).** `install-agent --agent
  qwen|kimi` writes skills + `QWEN.md`/`AGENTS.md`; `setup.sh` wires both
  skills and MCP for them in one pick. Codex, Antigravity, Qwen, and Kimi now
  share one `SkillInstructionConverter` base (Codex/Antigravity behaviour
  unchanged).

### Removed
- **Gemini CLI runtime removed.** Deprecated in favour of Antigravity; the
  embedding/summarization `gemini` provider (`GOOGLE_API_KEY`) is unaffected.

### Fixed
- **`setup.sh` no longer clobbers existing MCP configs.** The old hand-rolled
  MCP step (backup + overwrite, which destroyed other servers in a user's
  `.cursor/mcp.json` etc.) is gone; all MCP wiring now routes through the
  merge-safe `install-mcp --client`, in one multi-select that also runs without a
  project.
- **`install-agent` works on a standalone install.** The canonical plugin is now
  vendored into the CLI wheel at build time, so `install-agent --agent
  codex|opencode|antigravity|skill-runtime` no longer needs a repo checkout,
  Claude Code, or a manual `--plugin-dir` — it falls back to the bundled copy.

## [26.7.8] - 2026-07-18

### Added
- **Search guard covers Bash — scope-aware.** The PreToolUse guard now also
  reacts to recursive `grep`/`rg`/`ag`, but only when the target is content
  BrainPalace indexes; unindexed targets, single-file greps, and BM25-hostile
  regex pass untouched. A project shipping its own guard hook suppresses the
  bundled one.

### Changed
- **Search guard now defaults to `enforce`.** Grep is scope-aware like Bash —
  firing only on indexed content with a BM25-answerable pattern — and Glob is
  no longer guarded at all. Denials name the exact `brainpalace query` to run;
  soften with `cli.search_guard.mode: advisory`.

### Fixed
- **Orphan reaper no longer lies about "Reaped."** `reap_orphans` now
  escalates SIGTERM→SIGKILL and reports honest `reaped_pids`/
  `surviving_pids`; every server-side `git`/LSP spawn also routes through a
  `posix_spawn`-safe helper, closing the deadlock that pinned the listening
  socket forever.

## [26.7.7] - 2026-07-18

### Fixed
- **Docs no longer call `simple` the default graph store.** `GRAPH_STORE_TYPE`
  has defaulted to `sqlite` since the Phase 090 flip; ARCHITECTURE, USER_GUIDE and
  the skill's api_reference said otherwise. Also corrected the plugin command count
  (42 → 43) and the AI-guidance FULL tier size (~16 K → ~19 K).
- **Auto-router no longer lets a compute tell steal utterance-history queries.**
  "Which week did I mention retries most?" now excludes compute via new
  utterance-verb anti-tells, so scan owns it once a metric resolves — previously
  latent, masked only by empty-result fallthrough.
- **`--mode graph` is now reachable from plain `hybrid` queries.** A new
  `classify_graph_intent` auto-route leg (last in order, after timeline) reroutes
  relationship-shaped queries ("what calls X", "what depends on Y") to graph,
  logged at INFO; empty results still fall through to hybrid.
- **Compute/absence empty results now explain themselves.** Both modes read the
  typed numeric record store (populated only by session extraction, off by
  default); the CLI's empty-state prose now says so and points at `brainpalace
  records stats`, instead of reading like a plain search miss.
- **Removed the fictional `AuthService`/"auth decision" doc examples.** Neither
  entity exists in this repo, so the shipped graph/timeline examples returned
  nothing when run. Replaced with `QueryService`, verified live to return real
  results in both modes.

### Added
- **`routed_mode` tells you when your query ran in a different mode than you
  asked.** Set when the auto-router re-routes a `hybrid` query (compute/scan/
  absence/timeline/**graph**) or read-only degrades it to `bm25`; null otherwise.
  Graph re-routes were previously invisible (INFO log only); now surfaced in
  `--json`, the CLI header, and the dashboard replay panel.

### Changed
- **Scan mode now fans out across processes — ~9.7s to ~1.0s** on this repo's
  archive. Per-file counting moved to a lazily-created, reused pool
  (`min(8, affinity)` workers) once a scan touches 24+ files; fork-only, since
  spawn's re-import cost is worse than scanning inline. Private-session
  default-deny runs inside each worker.

### Added
- **AI guidance documents two query-mode gotchas.** Compute/absence need session
  extraction enabled or they return empty; `multi` silently drops its graph leg
  on a non-chroma backend (documented 3-way fusion becomes 2-way). Single-sourced
  in `ai_guidance.md`, regenerated into `SKILL.md`.

## [26.7.6] - 2026-07-17

### Fixed
- **`install-mcp` now makes Claude Code actually connect**, instead of leaving the
  server at "Pending approval". By default it registers in local scope
  (`~/.claude.json`), needing no approval or folder trust, and falls back to
  allowlisting `.mcp.json` without the `claude` CLI (`--scope` forces a route).

### Added
- **Rehome mints a fresh `project_uuid` and records lineage.** Every rehome (copy or move)
  mints a new `project_uuid` at finalize and records `parent_uuid` + `parent_index_root`, so
  each copy has its own chained identity (A ← B ← C) instead of inheriting the source's.
  Idempotent across resume.
- **Blocked-job reaper self-clears transient budget blocks.** A budget-BLOCKED job whose
  bloat source (e.g. a swept virtualenv) later shrinks or vanishes now revalidates on the
  heartbeat and resumes or dismisses itself instead of staying stuck until `--approve`.
  Never bypasses a genuine over-cap block.
- **`jobs --all` / dashboard "Show no-op runs" toggle.** No-op completed jobs (status=done,
  no chunk delta, no error) are hidden from the default listing so they don't evict real
  jobs from the paginated window; the reveal hatch plus a "N hidden" hint keeps it legible.
- **`brainpalace query --json` exposes `start_line`/`end_line`.** Nullable — only code
  chunks (~71% of the corpus) carry line numbers. AI guidance now also lists Bash `grep`
  alongside `find`/`rg` under "never search indexed source directly".
- **MCP `query` tool gains `file_paths`, `alpha`, `similarity_threshold`, `entity_types`,
  `relationship_types`.** Also fixes `top_k` to reject over 50, matching the server (was
  100, a 422 the schema should have caught first). This repo now ships `.mcp.json` too.
- **`brainpalace install-mcp`, called by `init` by default.** Merges the MCP server into
  any existing project `.mcp.json` without clobbering other servers (`--no-mcp` opts out).
  Tools arrive next session after approving the servers; `install-mcp`/`init` say so.

### Fixed
- **doc-sync no longer fails a correct doc over a `flag_value` default.** Introspection read
  `--project`'s raw `default=True` instead of Click's resolved `"project"`, so `install-agent`
  drifted permanently against an accurate doc — and `--fix` would have written the wrong fact
  in. Plain boolean flags are untouched.
- **`status` no longer replays a stale self-heal from a previous boot.** A healthy startup
  self-heal records no event, so the log's tail could be days old — surfacing a
  "N chunk(s) need re-embed" that no restart cleared. The row is now scoped to the running
  server's `started_at`; a real recovery still shows.
- **Dashboard "Re-run" now replays the SAME query.** A logged query's scope filters were
  dropped on replay, silently re-running a broader query; the server now logs every scope
  filter and the drawer + proxy forward them. The sensitivity gate stays un-proxied.
- **Self-heal no longer reports phantom "N chunk(s) need re-embed" for git.** The git
  wanted-set now keeps only the commits THIS store can account for — present live, or
  stranded in a dead segment (recoverable here, no re-embed). Never-materialized commits
  (fresh/reset/rehomed store, or ones the async boot-index job hasn't reached yet) are
  dropped per-id, not just when the whole git plane is empty — the always-enqueued,
  cache-backed git boot-index job rebuilds them.
- **Server "running" checks are identity-checked, not bare-200.** A server is a project's
  own only if `/health/`'s `project_root` matches — fixes a copied `.brainpalace/`'s
  `start` reporting false "already running", `list` phantom duplicates, and (highest
  severity) `stop` killing the ORIGINAL project's server.
- **Virtualenvs are pruned from indexing regardless of directory name.** Any subfolder
  containing `pyvenv.cfg` (the stdlib venv marker) is now skipped, not just `.venv`/`venv`
  — fixes a watcher-triggered reindex sweeping `.venv312`/`env`/etc. into the embed budget.
- **`cancel_job` now handles BLOCKED jobs.** Cancelling a budget-blocked job previously
  silently no-op'd; it now cancels immediately, same as a PENDING job — restoring the manual
  escape hatch for a stuck block.
- **Dashboard job "Type" column is git-aware.** A `git_history` job (which has
  `include_code=False`) was mislabelled "docs"; the column now renders a 3-way
  git/code/docs keyed on the authoritative `job_type` field.
- **Job detail surfaces its folder up top.** The indexed folder is now shown in the
  drawer header next to the status chips, not only at the bottom of the Details block below
  a possibly huge Files list.

## [26.7.5] - 2026-07-13

### Added
- **Project auto-rehome: move an indexed project, no re-embedding.** When the server
  detects its project moved on disk, startup prefix-swaps `old_root → new_root` across
  every path-addressed store (folder/manifest/chunk/graph/reference) before any
  destructive mutator; if it can't finish in-boot the instance enters QUARANTINE — a
  `503` gate serves only health/runtime/rehome and freezes
  prune/self-heal/watcher/job-worker. New `GET /rehome/` (status) + `POST
  /rehome/resume` (retry from checkpoint), surfaced by `brainpalace rehome`
  (status) / `--resume` / `--json`.
- **Per-section cost class (free / LLM / LLM/subagent).** Every config section
  now carries a cost badge so you can see at a glance whether enabling it invokes
  a model: `free` (no model), `LLM` (billable on a cloud provider), or
  `LLM/subagent` (always uses an LLM once on — free-tier Claude Code subagent
  quota or a billable provider). Single-sourced from `config_fields.GROUP_COST`,
  rendered as a header suffix in the `init` review grid (overview + drill) and as
  a badge on each dashboard Config section (`ui_schema` `SECTION_COST`).
- **`init` review grid: per-section description line.** Each config section in
  the interactive `init` overview now prints a one-line, width-truncated
  description under its header (dim, ellipsis-cut), sourced from the existing
  single-source `GROUP_DESCRIPTIONS`; the full text still shows when drilling in
  to edit. Sections without a description (embedding/reranker/…) are unchanged.
- **`scan`: bare single-word term under explicit `--mode scan`.** A one-word
  query now counts that word without needing quotes or a "mention" tell
  (`scan profile` == `scan "profile"`); multi-word stays strict, and the hybrid
  auto-router is unchanged (never guesses a term). Dashboard empty-scan hint +
  `docs/SCAN.md` updated to match.
- **`init` index-target picker.** A fresh interactive `init` that will index now
  asks — before the review grid — which folder to index (a path, or Enter for the
  whole project) and its type (code + docs / docs only), feeding the same targets
  as `-F/--folder` and `--include-code/--no-code`; either flag suppresses its prompt.
- **`brainpalace init`: interactive token-estimate ignore-loop.** After config, an
  interactive init shows a per-top-level-folder token breakdown of the index target
  and a menu to add/remove excludes (`indexing.exclude_patterns` or `.gitignore`),
  re-estimate, proceed, or cancel. `.gitignore` edits are immediate and permanent,
  an empty index is blocked, and `--yes`/non-interactive/CI print the estimate once
  and proceed (no menu).

### Fixed
- **Initial index no longer blocked by the embed-token budget cap.** A folder's
  FIRST index (no prior manifest) is now exempt from
  `indexing.max_embed_tokens_per_job` server-side, so a large project's initial
  index can exceed 100k tokens without pausing as `blocked`. The cap still guards
  every re-index, and each folder's first index is exempt independently across the
  multi-job init burst.
- **Self-heal no longer reports not-yet-indexed git commits as "need
  re-embed" residue** — the git wanted-set is now bounded by the git
  indexer's recorded `last_sha`, matching the manifest contract.
- **Dashboard Queries tab polish.** Compare-mode results now stack vertically
  (one full-width column per mode) instead of a 4-up grid; live "New query"
  results render the same path · score · snippet detail as the history drawer
  (was a bare file list); result snippet boxes get a higher-contrast scrollbar.
  An empty `scan` run now shows a term-extraction hint (quote the phrase / use a
  "mention" tell; `bm25` to locate rather than count) instead of the opaque
  "No aggregation rows."
- **Docs re-grounded to live code (4 files).** CONFIGURATION / SESSION_INDEXING /
  MCP_SETUP + `brainpalace-config`: dropped the removed `GRAPH_USE_LLM_EXTRACTION`,
  `session_extraction` drain knobs, `drain-tick`/babysitter, `extract-queue.txt`,
  the fictional `cache:` config block, LangExtract, and phantom
  `/brainpalace-providers`/`-embeddings`; MCP tool surface 9 → 12.
- **`init` token estimate now honours `.gitignore`.** The serverless pre-index
  estimate built a bare `DocumentLoader` with no `GitignoreMatcher`, so
  project-local ignores (e.g. `.planning/`) were counted even though the real
  index and file watcher skip them — inflating the file/token figure. It now
  builds the matcher via `GitignoreMatcher.from_project_root`, matching them.

## [26.7.4] - 2026-07-10

### Added
- **Enumerate ingested sources.** `GET /ingest/sources` (`brainpalace ingest
  sources`) lists distinct ingested source_ids with domain, source, chunk count
  and ingested_at; `GET /ingest/text/{source_id}` (`brainpalace ingest show`)
  pages through one source's chunks. Both honour sensitivity default-deny and
  return an empty list (not 404) for an empty index or unknown source_id.
- **HTTP writes for records and references.** `POST /ingest/records` and `POST
  /ingest/references` (and `brainpalace ingest record` / `ingest reference`)
  write the eager and lazy tiers over HTTP, routing through the same sink choke
  point as in-process adapters (replace-by-`source_id`, salience and provenance
  checks inherited). Both work without an embedding provider — references land
  unembedded and `references embed-missing` backfills them.
- **Full-forget cascade delete.** `DELETE /ingest/source/{source_id}` (and
  `brainpalace ingest --forget`) drops a source_id's document chunks, typed
  records and references in one call, reporting per-tier counts and bumping
  the query cache so a forgotten source stops appearing in cached results.
  `DELETE /ingest/text/{source_id}` keeps its narrower, published
  chunks-only meaning.
- **Query domain/metadata filters.** `QueryRequest` gains `domains` and
  `metadata_filter` (exact-match, AND across keys); `brainpalace query --domain
  D` (repeatable, OR) and `--meta k=v` (repeatable, AND) scope results to
  `/ingest`-tagged chunks. Both filters over-fetch Stage 1 candidates to
  preserve recall and are part of the query cache key, so different filters
  never share cached results.
- **Per-item sensitivity in `POST /ingest/text` batches.** Each item can now
  carry its own `sensitivity`, overriding the request-level default — a mixed
  batch (e.g. one private page among normal ones) no longer needs N separate
  calls. Omitting it falls back to the batch default, unchanged for existing
  callers.
- **Private memories.** Anything — records, graph nodes, sessions, curated
  memories — can now be marked sensitive and stays hidden from every search,
  recall, session-start injection, MCP client and the dashboard unless you pass
  `brainpalace query --include-sensitive`. Marking a session private also hides
  everything derived from it.
- **Memory that keeps itself tidy.** Curated memory no longer silently drops new
  facts when full — stale/superseded auto-saved entries are evicted, `remember`
  facts are never evicted, re-saying a fact replaces it instead of duplicating,
  and `brainpalace status` warns you rather than losing anything when it's full
  of your own facts. Automatic curation now follows your extraction setting and
  runs on a cadence (weekly by default), in-session or server-side.
- **BrainPalace knows who people are.** A new identity store keeps persons,
  their aliases and their links to accounts or repos, managed with
  `brainpalace entities`. Searches can be filtered and grouped by person, and
  ambiguous names come back as ranked candidates for you to confirm rather than
  being guessed at.
- **Search across other BrainPalace instances.** `brainpalace query --also
  <path-or-url>` (repeatable) fans a search out to sibling instances — e.g. a
  shared household or team instance — and merges the results, tagging each with
  the instance it came from. A sibling that is offline is skipped instead of
  failing the query.
- **Ingest any text, not just files.** `brainpalace ingest` (and `POST
  /ingest/text`) puts arbitrary text into the index with your own source labels;
  re-ingesting the same source replaces it, `--delete` removes it, and
  `brainpalace status` counts it. Unchanged text is never re-embedded, so
  re-ingesting costs nothing.
- **Reference search.** Lightweight reference summaries are now searchable with
  `brainpalace references search`, and the best ones surface directly in normal
  hybrid results. `references embed-missing` backfills older entries.
- **Docs rank below code by default.** A new `doc_weight` setting (default 0.5,
  editable in `init`, `brainpalace config` or the dashboard) makes source code
  outrank documentation in search results. **This applies to existing projects
  too** — set `doc_weight: 1.0` to keep the old behavior.
- **Folders can be marked as trusted or merely referenced.** `folders add` takes
  a domain and an authority (`authoritative` or `reference`); folders outside the
  project default to `reference` and rank below your own code unless you force
  otherwise. Existing projects are unaffected.
- **Faster, friendlier `init`.** `init -F/--folder <path>` (repeatable) indexes
  only the folders you name — including ones outside the project — instead of the
  whole project root, and `--no-start` just prints the commands. `init --start`
  no longer demands API keys for providers your configuration will never use.
- **`docs/BUILDING_ON_BRAINPALACE.md`** — a guide for building on top of
  BrainPalace: which interfaces are supported, how provenance works, connection
  modes, testing and versioning.

### Changed
- **New tagline.** BrainPalace now describes itself as a typed-memory and
  retrieval engine for AI agents — code and docs today, more domains coming —
  rather than "Vector Graph RAG for code & docs". Wording only, nothing behaves
  differently.

### Fixed
- Misleading error message when ingesting documents through the synchronous API,
  and a documentation hook that fired on unrelated files outside the project.
- **Stale cached queries after a POST ingest write.** `POST /ingest/text`,
  `/ingest/records` and `/ingest/references` now bump the query cache on
  success, matching the DELETE routes, so a write is visible to the next
  query immediately instead of waiting out the cache TTL.
- **Doc-sync `--fix` couldn't repair a command that lost all its flags** —
  the generator now normalizes a stale flags block to an explicit no-flags
  line instead of leaving it stale forever (dev-only tooling).

## [26.7.3] - 2026-07-05

### Added
- **Durable taught rules + salience seam (memory Phase 5).** Confidence rules
  now persist in `rules.db` (owner/version/retire) and load on start; `rules`
  CLI + `/rules` endpoints manage them. Records carry a write-time `salience`
  score with `register_salience_scorer` + a `records recompute-salience` path.

### Changed
- **Layer B prose verification now runs every release (marker gate).**
  `before-push` runs `lint:doc-verify` (`verify-docs --check`): fails unless the
  doc-verifier was run for THIS release's diff, so count/config prose drift can't
  accumulate unseen. Never blocks on an LLM verdict; the net-diff base defaults to
  the previous `release:` commit (`main` was degenerate — unrelated histories).

## [26.7.2] - 2026-07-05

### Added
- A generic cross-surface **parity harness** (`doc_sync/contract_parity.py`) plus
  the `query_modes` contract: the server enum is the single source of truth and a
  new gate (`ModeParityChecker`, in `lint:doc-sync`, and a fast `task test:cli`
  unit test) fails on any mode-set drift across the CLI Choice, MCP Literal, hook
  guard, or `MODE_META`, in either direction. Adds a dispatcher-completeness test.
- **Mode tables auto-generated from a single source.** README, USER_GUIDE,
  API_REFERENCE, and the plugin's `brainpalace-query.md` each keep their own
  richer column shape but now render from one `MODE_META` map
  (`doc_sync/mode_meta.py`), gated by `sync-docs --fix`/`--check` (and
  `lint:doc-sync`) — a new `--mode` value can no longer silently miss a doc.
- **`absence` query mode (Phase 3).** Deterministic no-LLM anti-join over the
  typed records store — subjects present under one partition value
  (`metric`/`source`/`domain`) but absent under another. Adds `--mode absence`, a
  `--json` `absence` field, a dashboard run mode, and a `records(source)` index
  (see `docs/ABSENCE.md`).
- **`timeline` query mode (Phase 4).** Deterministic no-LLM walk of an entity's
  edge-validity and supersession history in the knowledge graph, answering "how
  did X evolve" over the existing `search_nodes`/`timeline_named` surface with no
  new schema. Adds `--mode timeline`, a `--json` `timeline` field, and a dashboard
  run mode (see `docs/TIMELINE.md`).

### Fixed
- MCP `query` tool rejected the `compute`, `scan`, `absence`, and `timeline`
  modes (its `QueryMode` was a stale 5-value Literal). It is now **derived** from
  the server `QueryMode` enum, and the hook subagent guard + AI-guidance skill
  frontmatter were likewise brought to all 9 modes.
- **Release gate tests the release, not the last one.** Under
  `BRAINPALACE_RELEASE=1`, `cli:install` builds the cli venv against **local**
  server/dashboard source (restoring `poetry.lock`), so a new endpoint/module/
  config field no longer reads as false drift against the published sibling.

## [26.7.1] - 2026-07-04

### Added
- **Budget-blocked jobs — pause + approve.** An index job over
  `indexing.max_embed_tokens_per_job` now parks as `blocked` (nothing spent)
  instead of failing; approve via `brainpalace jobs <id> --approve`, the dashboard
  Jobs tab, or MCP `jobs_approve`. Surfaced in-band (`index_blocked`, `status`,
  `/health/status`, session-start); `--force-budget` bypasses on first index.
- **Adaptive budget cap.** The per-job cap scales with project size —
  `max(max_embed_tokens_per_job, max_embed_ratio_per_job × estimated index size)`
  (ratio default `0.2`, env `INDEX_MAX_EMBED_RATIO`, `0` = fixed cap). The 100k
  value becomes the floor, so big repos stop tripping on legitimate churn.
- **`scan` query mode (memory Phase 2):** deterministic term counts over the
  archived session transcripts, bucketed by week/month/day/source, answering
  "which week did I mention X most" with no LLM cost; auto-routes from hybrid
  on utterance-history tells (compute wins ties); empty when the session
  archive is off.
- **Graph query surface.** New `GET /graph/path|impact|cochange|top` endpoints and
  `brainpalace graph path|impact|cochange` verbs (SQLite store, no chroma); `--mode
  graph` matches via store search and orders by edge `weight` (absent = 1.0), with
  impact/co-change sections in the dashboard node detail.
- **Richer code graph.** Now models files/folders, precise node kinds (class,
  function, method, enum, interface, decorator, API endpoint), real imports, package
  deps, route→handler links, and an **exact call graph** — cross-file calls resolve
  precisely with a language server (`graph_indexing.lsp`). Doc/session mentions link
  onto canonical code nodes (Plan B); git-history adds `Commit modifies File`/
  `authored_by Author` edges + co-change (Plan C).
- **Graph browser + no-reembed rebuild.** The Graph tab opens at the top hub with a
  node detail panel (source, callers/callees, lazy snippet via
  `GET /graph/node/source`), curved labelled edges, a kind→color legend, and
  kind/edge/domain filters. `brainpalace index --rebuild-graph` and a **Rebuild code
  graph** button rebuild the AST+LSP graph from indexed chunks — no embedding, no
  token cost.
- **Language-server install on enable.** Turning on graph/LSP offers to install pyright
  via pipx / npm / in-venv pip; new `brainpalace lsp install [--yes]`, `doctor`/`init`
  prompts (never auto-installs non-interactively), and `status` flags a
  configured-but-missing language. Python only.

### Changed
- **Graph browser rebuilt.** Search results open in a slide-in panel; the canvas is
  a live force-directed layout (Obsidian-style) that settles and clusters related
  entities — click to recenter, drag to reposition, labels hidden until zoomed or for
  hubs so large graphs stay readable.
- **Subagent guard defaults to `enforce`, scoped to search-shaped spawns.** The
  PreToolUse `cli.subagent_guard` acts only on `Agent`/`Task` prompts that are an
  actual codebase-search task (intent gate), so it denies a directive-less search
  spawn by default without blocking non-search agents. Soften with
  `cli.subagent_guard.mode: advisory` / `BRAINPALACE_SUBAGENT_GUARD=advisory`.

### Fixed
- **Plugin safety & reliability hardening.** The setup wizard asks before
  changing permissions and grants far less, assistants get only the tools they
  need, session context can't smuggle in hidden instructions, and setup, install,
  and database defaults are safer and more robust.
- **`indexing.exclude_patterns` can exclude individual files, not just directories.**
  A pattern naming a file was silently ignored — only directory subtrees were pruned
  — so a big churny file kept re-embedding on every change. Project-set patterns now
  **extend** the built-in defaults instead of replacing them, so excluding one file no
  longer drops the `node_modules`/`.venv` defaults.
- **Code graph correctness (Plan 4).** Removed self-loops, duplicated parent/child
  edges, and a bogus funnel hub so real callers/callees and entry-point paths are
  reachable, with class-qualified method names and merged same-named variants.
  Built front-end bundles are no longer indexed as fake hubs; requires a graph re-index.
- **Code graph build hardening (Plan 4).** Fixed graph-build crashes on real chunks
  (`ChunkMetadata.get`, self-loops, parallel edges), stalled hub expansion, the
  white-on-white tooltip, and `add_triplet` failing on the `simple` backend. Exact
  edges now carry `source_chunk_id` (`--mode graph`) with per-endpoint domains so
  cross-domain edges never flip a node's domain; the canonical-identity rebuild runs
  automatically on the next index.
- **Code graph — LSP live-fidelity (Plan 5).** The LSP layer runs against a real
  language server: the indexed root is the workspace (`rootUri`), files are opened
  (`didOpen`) before querying, and requests time out instead of hanging. Cross-file
  targets resolve to qualified `file:Class.method` ids that merge with AST nodes;
  churny `defined-at`→`Location` edges are gone; servers shut down
  after each build and `BRAINPALACE_LSP_LANGUAGES` changes apply without a restart.

## [26.6.54] - 2026-06-28

### Added
- **Plugin SessionStart install prompt.** When the plugin is loaded but the `brainpalace` CLI is absent, the SessionStart shim offers installation (AskUserQuestion → `/brainpalace-setup` or `/brainpalace-install`) every session until the CLI exists, instead of failing silently; a CLI-present-but-unindexed git project gets a one-time setup offer. Opt out with `BRAINPALACE_SETUP_NUDGE=off`.
- **Activation gate — plugin configures, you start.** `brainpalace init --defer-activation` (the plugin path) writes config but leaves the project NOT running, arming `cli.await_first_start` so passive vectors (the SessionStart hook, MCP `--ensure-server`) won't auto-start it and the hook nudges "configured but not running". The first manual `brainpalace start` (or dashboard Instances → Start) clears the gate; bare terminal `brainpalace init` is unchanged.

## [26.6.53] - 2026-06-28

### Added
- **Graph browser: start with no search.** The dashboard Graph tab gained a "Start graph browser" button that opens the graph at its most-connected entity (the hub) and lists the top hubs as alternative seeds — no need to know a search term first. Backed by `GET /graph/top` (highest active-edge-degree nodes; 503 when graph indexing is off).
- **Usage telemetry.** New dashboard **Usage** tab — LLM in/out/cache + embedding tokens, call/chunk/triplet totals, per-source queue depth, and hourly trends — backed by `GET /metrics/usage` and the `usage_metrics` config (`enabled`/`retain_days`). Providers gained `*_with_usage` siblings exposing token counts.
- **Unified extraction engine (`extraction.mode`).** One `extraction:` section (`mode` off/subagent/auto/provider + grace/drain knobs) drives both doc-graph triplets and session distillation; triplets drain off a deferred per-chunk queue in throttled batches (no LLM burst at index time). Default `off` is the cost lock; the paid provider also needs `EXTRACTION_PROVIDER_ENABLED`.
- **Automatic free doc-graph drain.** The `UserPromptSubmit` hook drains `/extraction/pending?source=all` each prompt — doc-chunk ids → the free Haiku `graph-triplet-extractor`, session ids → `chat-session-extractor` (per-source caps, 5-min cooldown). Agents submit via `extraction_fetch`/`extraction_submit`; the doc agent has no Bash and fetches text by id, so untrusted indexed text never reaches a shell.
- **Global config: per-field scope + provenance.** Each registry field carries a `scope` (`both`/`project`/`global`); `init --global` and the dashboard Global tab omit project-scoped fields. The project editor shows an "inherited from global" note from true project/global/default resolution, and `lint:config-parity` checks every spec's scope.
- **Incremental session resume.** A resumed session re-distils only its new turns and merges them into the existing summary (decisions/triplets deduped) instead of re-summarizing the whole transcript. Non-resumed sessions are unchanged.
- **Unified config field registry (single source).** `config_fields.py` derives one spec per pydantic config field (group/order/help/label/options/role); the dashboard Config tab, `init` review screen, and `config wizard` all read it, so `bp init` and the dashboard render identical sections and can't drift. A `lint:config-parity` test guards it.

### Changed
- **Grouped `.brainpalace/` state layout.** Durable SQLite stores now live under `db/` (`query_log`, `usage_metrics`, `records`, `extraction_pending`) and small cursors/markers + audit-event jsonl under `state/`, keeping the state-dir root to user-facing files. **Breaking on upgrade:** there is no migration, so an existing install's flat-root folder manifest / git-index cursor / query log are not relocated — re-index to restore folder & watch tracking (vector/BM25 data under `data/` is unaffected).
- **Config overview readability.** `brainpalace init`'s overview truncates long values (e.g. `exclude_patterns`) past ~70 chars (full value still shown when editing); sections were renamed (`Chat Session : …`, `Compute Query`, `Server`/`Server Mode`) and reordered (providers → retrieval → storage → session → server → logs). Display-only; the dashboard mirrors it via the shared registry.
- **Unified config editor.** `brainpalace config wizard` is now a back-compat alias of `brainpalace init`'s editor (the bespoke 12-step wizard is removed). `init --global` edits the XDG global config (validated, atomic, no-op on identical content); reranker/lemma extras auto-reconcile after review edits; the fresh-init token estimate runs after the review screen.
- **`init` asks before starting + registers for the dashboard.** A bare interactive `brainpalace init` now asks "Start the server now?" (decline = config-only), and every init registers the project in the known-projects store so it's listable/startable from the dashboard even when not started.
- **Graph query separated from the build switch.** A `graph`-mode query now returns empty (like `bm25`/`vector` on an empty index) when no graph is built, instead of raising "GraphRAG not enabled". `ENABLE_GRAPH_INDEX` still gates building the graph and the `rebuild_graph` endpoint.

### Fixed
- **Usage tab: anchor the time window to the newest data, not wall-clock.** A `1h` (or any) window previously showed nothing during a quiet hour; `GET /metrics/usage` now anchors `since` to the most recent recorded minute bucket (`UsageMetricsStore.latest_bucket()`), so it always shows the last window's worth of actual log data. Falls back to wall-clock when the store is empty.
- **Usage queue-backlog widget: split git out + flag off features.** The dashboard "Documents" backlog merged doc-file and git-commit chunks; git now reports as its own "Git history" row (`doc_pending` gained a `kind` column, auto-migrated). Each row is flagged "not draining" when its draining feature is off, so a permanent backlog isn't shown as work-in-progress.
- **Extraction & session-resume hardening.** Drain agents run tool-less (no Bash) so hostile indexed-chunk text can't reach a shell. Resume merge is structural (no LLM) — set-union of decisions/triplets/summaries — so earlier knowledge can't be paraphrased away; plus a per-session distill lock, atomic marker/sidecar writes, and bounded queue endpoints.

### Removed
- **Removed all compute query-mode switches.** Compute now behaves like `bm25`/`vector` (always selectable, empty when no records), and records extract automatically when session extraction runs. **Breaking:** `compute.enabled`/`ENABLE_COMPUTE`, `compute.record_extraction`/`RECORD_EXTRACTION_ENABLED`, and the `--compute` init flag + prompt are gone; only `compute.min_confidence` remains.
- **Removed `brainpalace drain-queue` + the legacy session-only auto-drain.** Superseded by the unified per-prompt drain over `source=all`. The manual `/brainpalace-drain-graph` and the SessionStart backlog nudge are likewise removed — doc drain is now automatic.
- **Removed code summarization (`--generate-summaries`).** It was never embedded or queried, so removal has no retrieval effect. **Breaking:** the flag, `generate_summaries` field, `summaries_enabled` estimate, and `section_summary` injector keys are gone.
- **Removed the broken langextract doc extractor + inert config.** `LangExtractExtractor` called `langextract.extract_relations`, absent in 1.1.1 — doc-chunk graph extraction was a silent no-op for `--extras graphrag`. Removed the class, the `langextract` dep, the `graphrag` extra, and the dead `GRAPH_DOC_EXTRACTOR`/`GRAPH_LANGEXTRACT_*`/`doc_extractor` keys (Code-AST extraction unaffected).

## [26.6.52] - 2026-06-24

### Added
- **Compute query mode (`--mode compute`).** Answers set-level questions over your sessions — sum/count/average, grouped by ISO-week or month, and "which … the most" superlatives — over typed numeric records instead of documents. Auto-routed from a plain question, with a hybrid-search fallback. (Phase 1)
- **Typed numeric records.** A dedicated SQLite store captures per-session numbers: deterministic HIGH-confidence counts (files touched, tools used, decisions, open threads) derived **free** from the session summary, plus optional LLM-extracted records — all confidence-tiered so only trusted values sum. (Phase 0)
- **Compute config + setup surfaces.** `compute.enabled` / `record_extraction` / `min_confidence` (kill-switches, default ON, no extra API cost) are surfaced in config, the dashboard, `brainpalace init` (`--no-compute`), the `config` wizard, `brainpalace records`, and `brainpalace status`.

## [26.6.51] - 2026-06-23

### Added
- **Dashboard config moved to its own `dashboard.yaml`.** The dashboard's settings
  now live in `~/.config/brainpalace/dashboard.yaml` (auto-migrated from the legacy
  `config.yaml` `dashboard:` block) and are written sparsely; the Settings tab uses
  the shared inherit-first control.
- **Dashboard: one inline inherit-first control everywhere.** Every config field
  (instance Config, Global, Settings, Runtime) renders as one always-visible row:
  `(•) using <global|code default>: X  ( ) <choices / input>`. Pick the inherited
  value, a choice, or type one — the separate "Override" button is gone.
- **Dashboard: Runtime bind folded into Config + a real global layer.** The
  standalone Runtime tab is removed; `config.json` bind fields edit inline in
  Config (project > **global** > code default), and a machine-wide bind editor
  lives on the Global tab. The CLI honors the global defaults (XDG `config.json`)
  at server start; new `…/runtime-config/effective` + `global-runtime-config` routes.
- **Dashboard: nothing persistable is silently missing.** Init-managed identity
  paths (`state_dir`, `project_root`) render **read-only** instead of hidden.
- **Dashboard: session config split into three clear sections.** The old
  "Session Indexing" (which buried the archive as a sub-group) is now **Session
  Archiving** (the raw copy), **Session Vector Indexing** (the embed), and
  **Session Summarization** (the LLM distill, was "Session Extraction"). Display
  only — config keys are unchanged (`session_indexing.archive.*`,
  `session_indexing.*`, `session_extraction.*`).

### Added
- **Index-drift warnings (embedding provider/model + storage backend).** An
  existing-index vs effective-config mismatch (embedding `provider`/`model`/dimensions,
  previously log-only) is now surfaced in `brainpalace status` (⚠ Index-drift panel),
  `/health/status` (`index_warnings`), and a dashboard banner. A new storage-backend
  drift check warns when `storage.backend` changes while data is stranded under the
  old store (BM25 self-heals, so it needs none).

### Changed
- **Dashboard config form is now generated from the server pydantic models.** A new
  `model_introspect` layer derives each field's widget/default/enum from its model —
  add/change/remove a model field and the dashboard follows; `ui_schema.OVERRIDES` is
  now presentation-only and the hand `_INT/_BOOL/_DICT/_STRINGLIST`/`DEFAULTS`/`ENUM_OPTIONS`
  tables are gone. GraphRAG's legacy/internal knobs moved to `DASHBOARD_HIDDEN_FIELDS`
  (with reasons) so a new graphrag field auto-surfaces, and the parity gate now sources
  from the models and fails on control/default drift.
- **Session recall is gated on the live feature flags (hard off).** With session
  vector indexing off, `session_turn` chunks are hidden from every query; with
  summarization off, `session_summary`/`session_decision` chunks and auto-promoted
  (`origin != user`) memory are hidden — no per-query override. The SessionStart block
  drops session-derived memory and emits its recall instruction only when a feature is
  live (`brainpalace remember` facts unaffected); new **Session Recall** row in `status`.
- **Dashboard SPA no longer committed to git.** The built `static/` is now
  gitignored generated output, rebuilt from frontend source at wheel-creation (new
  Node step in the `publish-dashboard` job) and on `task install`; pyproject
  `include` still packages it into the wheel, so end users get a prebuilt SPA with
  no node toolchain. Ends worktree churn on every rebuild.

### Fixed
- **Embedding provider mismatch no longer false-fires.**
  `str(EmbeddingProviderType.OPENAI)` yields the enum repr, not its value
  `openai`, so the index-vs-config provider check always mismatched and every
  query 409'd on an unchanged config. All comparison/message/cost sites now use
  the enum value.
- **A dead dashboard is now resurrected on the next session.** The dashboard is
  launched by `brainpalace start` but unsupervised, and SessionStart autostart only
  fired when the *server* was down — so a dashboard stopped while the server ran (e.g.
  a reinstall) stayed down. The SessionStart hook now also relaunches it (detached,
  best-effort, gated by `dashboard.autostart`) when the server is up but the dashboard
  has died.
- **Dashboard instance Config always shows the inherited value (never blank).** The
  inherit-first option on the instance Config / Runtime tab now falls back to the
  code default when the global config does not set the key — shown and selected,
  labelled "using code default: X" — instead of hiding the option and leaving the
  field with no selected value. A real global value still reads "using global
  value: X"; a field with no parent value at all (e.g. an api_key_env with no code
  default) still shows just the input.
- **Dashboard config save no longer false-blocks a no-op as "incompatible with
  indexed data".** Writing a key to the value it already inherited (e.g.
  `embedding.provider` null → openai when openai was already the effective
  default) left the embedding/store identity unchanged, yet the data guard
  compared the raw project value and raised a 409. The guard now compares the
  EFFECTIVE value (project > global > code default); a global save is likewise a
  no-op for an instance that overrides the key at project level.
- **Dashboard save keeps the config sparse (no inherited-default pollution).** The
  form submits a field's effective value even when it only inherits it, so a save
  could write e.g. `embedding.model` at its code default into a project file that
  never set it — un-sparsing it and making every later save diff it as a change.
  The write now drops a NEWLY-added leaf that equals the value it would inherit
  (global → code default); a value that diverges, or one already on disk, is kept.
- **Dashboard no longer drifts off its port (8787 → 8788) on restart/reinstall.**
  The free-port probe now binds with `SO_REUSEADDR` — exactly how uvicorn binds —
  so a just-stopped dashboard's `TIME_WAIT` socket on the configured port reads as
  free and the restart reclaims it, instead of falsely seeing it busy and climbing
  to the next port. A genuinely foreign listener still makes the scan climb.
- **Session archive / vector-index / summarization are now truly independent.** The
  reconciler fed the server-side summarizer (provider/auto mode) only the *archived*
  copies, so turning the archive (copy) OFF silently stopped summarization even when it
  was enabled. It now summarizes the live source transcripts when archive is off, and the
  server builds the distiller when extraction is on even if archive and index are both off.
  (Vector indexing already read the live source; the subagent extractor was always
  independent.)
- **Reranking default now actually OFF in the config model.** `RerankerConfig.enabled`
  and the dashboard's `reranker.enabled` default were still `True` while `init` and the
  docs already treated reranking as opt-in; flipped to `False` so an unconfigured server
  (no `config.yaml`, no `ENABLE_RERANKING`) matches the documented OFF-by-default.
- **Dashboard: edits stay staged until Save.** Reverting a field to its inherited
  value no longer writes immediately — it stages an unset sent with the next Save
  (`PATCH …/config` now takes `unset`), so **Discard** and a browser refresh fully
  revert it. Override/inherit state is driven by the live draft, not the server.

## [26.6.50] - 2026-06-20

### Added
- **Durable human-confirm for doc-prose claims (repo-dev).** `brainpalace
  verify-docs --confirm <doc>…` records a "mark verified by human" order in a
  checked-in ledger (`scripts/doc_verify_confirmed.json`) and re-settles in the same
  call, flipping a doc's open external (`unresolved`) claims to SUPPORTED/`audit`
  tier immediately. The order survives later `--record` sweeps; code/doc-dep claims
  are refused — code stays ground truth.

### Fixed
- **Doc-verify PostToolUse nudge mirrors `_is_excluded` (repo-dev).** Editing an
  excluded doc (CHANGELOG / ORIGINAL_SPEC) wrongly nudged "run Layer B" — which the
  verifier silently skips; the hook now points those to a freshness re-stamp instead,
  and emits nothing for excluded scratch trees (superpowers/.planning).
- **`--no-dashboard` now holds for the server's whole lifetime.** It was only
  silencing the CLI launch; the server's self-heal still re-spawned a dashboard
  (autostart defaults on), racing an external manager and drifting the port
  (8787 → 8788). The flag now also gates self-heal (`BRAINPALACE_NO_DASHBOARD`).
- **Dev install-from-source (repo-dev).** Fresh-build the local CLI/server/dashboard
  (`--no-cache-dir`) so a stale path-keyed wheel can't downgrade them; the version
  probe no longer aborts the whole task (`set -e`) when `/health` omits a version.

### Changed
- **doc-verifier doc-dependent claims (repo-dev).** A prose claim may now rest on
  another **audited** doc (`doc-dep`); a settle fixpoint confirms it only while every
  dependency is fully clean, else a silent `PENDING`, and re-grounds it when that doc's
  authored body changes. Genuinely stuck cycles surface to
  `.claude/doc-verify-needs-human.md`; the old BLOCKED defer scheduler is removed.
- **doc-verifier `audit` grounding tier (repo-dev).** An `unresolved` claim (no code
  path, no audited-doc dep) in an **audit-fresh** doc is now recorded SUPPORTED on the
  `audit` tier — a human-vouched external fact counted clean instead of re-flagged
  `UNVERIFIABLE`, provenance on `grounding_tier` not the status. Fails closed — editing
  prose without re-stamping drops it to `UNVERIFIABLE`, `CONTRADICTED` is never promoted,
  and precedence stays code > doc-dep > audit > unresolved.
- **doc-verifier self-reference fix + `--resettle` (repo-dev).** `_grounding_tier` now
  treats a grounding that names only the host doc as a self-reference (`unresolved`),
  matching `_doc_paths_from_grounding`, so a self-cite settles via the audit tier instead
  of mis-classifying as `doc-dep`. New `verify-docs --resettle` re-runs only the
  deterministic tier + settle pass over cached raw verdicts (no LLM) when a settle input
  moves — a classifier fix, a dependency going clean, or an audit stamp — re-stamping only
  docs whose outcome changed.

---

## [26.6.49] - 2026-06-18

### Added
- **doc-verifier relation-driven re-verification (repo-dev).** `verify-docs
  --record` stores `grounding_files` and a content hash per claim; a doc is
  skipped only while its prose and every grounded file/dir are unchanged — so
  token use tracks real change, not a calendar. Doc-grounded claims are
  `UNVERIFIABLE`; `--skip-fresh`/`--reset` are removed (full re-verify:
  `--all --force`).
- **Doc-verifier code-first grounding (repo-dev).** A prose claim supportable only
  via an unverified doc is `BLOCKED` and deferred until that dependency verifies;
  cross-dependent cycles surface once in `.claude/doc-verify-blocked.md` instead of
  being re-queued every batch.
- **Doc-verifier stops on a dead server (repo-dev).** Before judging, the sweep
  pre-flights the index server and attempts one restart; if it stays unreachable it
  aborts (records nothing) instead of grounding against nothing. The agent likewise
  treats a query error as abort-not-`UNVERIFIABLE`.
- **Doc-verifier grounding hardened (repo-dev).** Tier classification fails closed
  (only a real source path earns `code`; unknown `.md`/empty grounding can't);
  CHANGELOG, ORIGINAL_SPEC, `docs/superpowers/`, `.planning/` are excluded as
  grounding sources; verdict cache writes are atomic and refuse to silent-wipe.
- **Search guard.** A PreToolUse hook steers the main thread's `Grep`/`Glob`
  toward `brainpalace query` (advisory nudge by default; opt into `enforce` to
  deny) when the project is indexed and its server is up. Knobs
  `cli.search_guard.*` / `BRAINPALACE_SEARCH_GUARD`; Bash unguarded (escape hatch).
- **Source builds flagged across surfaces.** `brainpalace --version`, `brainpalace
  status` / the dashboard "Server version" (server `/health`), and the dashboard
  footer append `(from source)` for a local-path install; the Status tab also
  surfaces the control-plane dashboard version. Released wheels show plain numbers.

### Fixed
- **Hook shims fail soft under version skew.** When the plugin is newer than the
  installed CLI (no `hook` command yet), the SessionStart/UserPromptSubmit/
  PreToolUse shims now no-op silently instead of surfacing an error that blocked
  every prompt and tool spawn.
- **`/health` version assertion tolerates the source-build suffix.** The health
  test pinned `version == __version__`, which broke on editable/source checkouts
  that append `(from source)`; it now matches the prefix.

### Docs
- **Full audited-doc prose-verification pass.** Re-grounded the audited doc set
  against live code and corrected drift: `init` session-embedding is opt-in (not
  "both ON"); MCP-client/timeout and graph-load notes degated from ungroundable
  specifics; USER_GUIDE/CONFIGURATION/QUICK_START counts, modes, and presets
  refreshed.

---

## [26.6.48] - 2026-06-16

### Added
- **Auto-start the server on Claude Code session start.** When a session opens in
  an indexed project whose server is down, the SessionStart hook spawns
  `brainpalace start` detached (server + headless dashboard, no browser). On by
  default; disable with `cli.session_autostart: false`; fail-soft, never blocks
  the session.

### Changed
- **AI-guidance directive routes by query type, not a blanket "prefer brainpalace
  over grep".** Exact symbol/token/path lookups now point at `--mode bm25`, so
  brainpalace-first costs no latency vs grep; vector/hybrid stay for conceptual
  queries. Regenerated `SKILL.md`; bumped `ai_guidance.md` to 7.4.0.
- **Plugin-update command shown in a red-bordered box during `scripts/setup.sh`.**
  The `claude plugin update brainpalace@brainpalace-marketplace` line now stands
  out in Step 2/6 and is repeated in a box at the end of the install summary so it
  survives a long scroll instead of blending into the `==>` log.

## [26.6.47] - 2026-06-15

### Added
- **Plugin-docs doc-sync gate.** `lint:doc-sync` now folder-scans plugin agents,
  skills (`SKILL.md` + references) and the plugin `README.md` for dangling
  command/skill references and **fails closed** on any unregistered new doc, so a
  new agent/skill can't enter ungated.
- **Generated provider/install tables.** Provider and runtime install-dir tables
  now regenerate from the live registries via `<!--GENERATED-->` blocks;
  `lint:doc-sync` fails on drift. Converted across README, user/plugin guides,
  setup-assistant + install-agent (fixed stale `GOOGLE_API_KEY`/`GROK_API_KEY`).

### Changed
- **Doc-sync dev tooling no longer ships to end users.** The
  `authoring-brainpalace-docs` skill and the PostToolUse doc-sync nudge moved from
  the distributed plugin to repo project scope (`.claude/skills`,
  `.claude/settings.json`); the gate's `SkillsChecker` now also scans
  `.claude/skills` so refs still resolve.

---

## [26.6.46] - 2026-06-15

### Fixed
- **`start` reuse-live-server path now shows the dashboard URL box.** When a
  running server was reused, the dashboard URL panel was skipped; it is restored
  so the URL surfaces on every start path.

---

## [26.6.45] - 2026-06-15

### Fixed
- **Plugin version now tracks cli/server in lockstep.** `plugin.json`'s `version`
  (the freshness key `brainpalace plugin status` / the `update` tail read at the
  release tag) was frozen, so users were never offered `claude plugin update` even
  when plugin hooks changed. The release now bumps the plugin manifest + the
  marketplace entry too, guarded by `test_version_consistency.py`.
- **`brainpalace update` verifies shutdown before upgrading.** The pre-upgrade
  stop was fire-and-forget SIGTERM and returned before processes died, so the
  install ran over still-live old code. It now polls for real exit, escalates to
  SIGKILL, and on a stubborn survivor warns and offers retry-or-continue.

---

## [26.6.44] - 2026-06-15

### Added
- **Plugin version awareness on update.** `brainpalace plugin status` and the
  `brainpalace update` tail now report installed-vs-latest-release plugin version
  (`version`/`latest`/`update_available` in `--json`) and, when behind, ask before
  running `claude plugin update` with a red "restart Claude Code" notice. Fail-soft
  and offline-safe.

### Changed
- **UserPromptSubmit drain hook is now a thin shim.** Its logic + injected
  directive text moved into the CLI (`brainpalace hook userpromptsubmit`), matching
  the other three hooks, so a `pip` upgrade propagates wording changes and the
  shim can't drift. Behavior is unchanged; one `whoami`/discovery call instead of
  two, no inline `python3` heredoc.
- **Subagent guard defaults to `advisory`, not `enforce`.** The PreToolUse guard
  is still ON while the server runs but now NUDGES rather than DENYING spawns by
  default, so it no longer silently blocks other plugins' agents. Opt into hard
  blocking via `cli.subagent_guard.mode: enforce` / `BRAINPALACE_SUBAGENT_GUARD=enforce`.
- **Subagent guard accepts MCP query directives.** A spawn prompt now satisfies
  the guard with either the CLI `brainpalace query ... --mode <mode>` form or the
  MCP/skill `query` tool's `mode:` argument — fixing false denials of MCP-only
  search subagents.

### Removed
- **Retired `sessionend-hook.sh`.** The SessionEnd extract-queue hook (a no-op
  since summarization went archive-driven) is deleted and unregistered from the
  plugin `plugin.json`. Session knowledge extraction is unaffected — it runs from
  the `UserPromptSubmit` drain hook.

## [26.6.43] - 2026-06-14

### Added
- **Subagent guard.** A new opt-out `PreToolUse` hook (`brainpalace hook
  pretooluse`) denies (`enforce`, default) or nudges (`advisory`) `Agent`/`Task`
  spawns whose prompt lacks a `brainpalace query --mode` directive — on by
  default but active only while the project server runs, with `research-assistant`
  allowlisted. Disable via `cli.subagent_guard.enabled: false`, `allow_agents`,
  or `BRAINPALACE_SUBAGENT_GUARD=off`.

### Changed
- **Dashboard Jobs table shows the content scope.** The "Type" column previously
  read `index` for every row; it now appends the scope (`code` vs `docs`) so a
  job's purpose is visible without opening it.
- **`brainpalace status` shows the server URL + a dashboard box.** The top
  "Server Status" panel now includes the (clickable) server URL, and a pink
  "Web Dashboard" box is always shown — a clickable URL when the dashboard is
  running, or a clear notice when it's stopped/not installed. `--json` gains
  `health.url` and a `dashboard` block.
- **`config wizard` pre-fills from the saved global config.** Re-running the
  wizard (e.g. during install/update) now seeds every prompt default from your
  existing `~/.config/brainpalace/config.yaml`, so pressing Enter keeps current
  choices instead of silently resetting to shipped defaults. Falls back to the
  shipped default per key when absent; first-time runs are unchanged.
- **`research-assistant` agent is now BrainPalace-only.** `Glob`/`Grep` are
  disabled (`tools: Bash, Read`) so the research agent cannot fall back to
  filesystem grep; pair it with the subagent guard for codebase-search subagents.
  AI guidance now routes code-search subagents to `subagent_type:
  research-assistant`.

### Fixed
- **No more double SessionStart when the plugin is installed.** `init` /
  `install-session-hooks` are now plugin-aware: if the Claude Code plugin is
  present (it provides hooks via `plugin.json`), the CLI installs no SessionStart
  shim and removes any CLI shim a prior version left — fixing duplicated
  session-start guidance. CLI-only users still get the reminder, and `init` prints
  a short hint to install the plugin for the full integration.
- **Plugin update needs the qualified name.** `claude plugin update brainpalace`
  fails with "not found" (and misleadingly exits 0); use
  `claude plugin update brainpalace@brainpalace-marketplace`. The `init` hint now
  shows the qualified command.
- **Dashboard no longer drifts off its configured port on restart.** A reaped
  dashboard could still hold the port (e.g. 8787) when the relaunch scanned,
  causing it to climb (8787 → 8789). Launch now waits for the configured port to
  free — escalating a stubborn reaped process to SIGKILL — so a restart always
  reclaims the configured default instead of drifting.
- **Session titles skip IDE/system context wrappers.** The archive list (and
  dashboard Sessions table) derived a title from the first user line, which could
  be an injected `<ide_opened_file>…` / `<system-reminder>…` wrapper. Title
  derivation now skips `<…>` wrapper lines and uses the first real typed line of
  the turn.

---

## [26.6.42] - 2026-06-14

### Fixed
- **Two dashboards (one empty) no longer spawn from a test run.** Reaping is
  scoped to the active `XDG_STATE_HOME` and launches don't detach under pytest,
  so a test can't kill or leak your real dashboard; a zombie child now reads as
  dead so it can't poison the singleton pidfile.

---

## [26.6.41] - 2026-06-14

### Added
- **`task release:rehearse-ci` reproduces the dashboard-absent publish gate.** The
  publish/PR-QA CI runs in a server+cli env with no dashboard installed, so
  dashboard-coupled code can pass `before-push` yet fail CI; the new task forces
  that env both ways — `BRAINPALACE_DOCSYNC_NO_DASHBOARD` for the doc-sync paths
  and a `sitecustomize` import-blocker (`BRAINPALACE_BLOCK_DASHBOARD`) that makes
  `import brainpalace_dashboard` raise — then runs `lint:docs-gates-ci` + server
  & cli tests as CI does, surfacing that class of failure before a release is cut
  (RELEASING.md step 8a). `task before-push` now runs it automatically, so the
  rehearsal can't be forgotten.
- **CI now validates the dashboard for real (new `Dashboard Gate` job).** The
  publish + PR-QA workflows gained a Python 3.12 job that installs all three
  packages and runs the FULL `lint:doc-sync` + `lint:dashboard-parity` with the
  dashboard present; the 3.11 server+cli gate still skips `/dashboard` checks, so
  together they cover both without false-fails, and publishing now waits on it.

### Changed
- **Doc-freshness now gates on a content hash, not a commit date.** `lint:doc-freshness`
  compares each audited doc's authored content against a sha256 in the sidecar
  manifest `scripts/doc_freshness.json`, closing the blind spot where an edit made
  the *same calendar day* as validation passed the date check. `last_validated`
  stays a human frontmatter date; the hash lives in the manifest so docs render
  clean on GitHub.
- **Changelog lint gains a 320-char per-entry cap.** A backstop against run-ons
  that dodge the 3-sentence cap by joining clauses with `;`/`—`; enforced on
  `[Unreleased]` entries only, so already-versioned sections never fail
  retroactively.

## [26.6.40] - 2026-06-14

### Added
- **Interface doc-sync gains an AI authoring layer.** A new
  `authoring-brainpalace-docs` skill plus a PostToolUse soft-nudge (fired when an
  interface-source file is edited) drive in-session prose authoring of the
  residual human regions — the CLI still never calls an LLM. `sync-docs --check`
  now asserts the dump/checker `schema_version` match and wraps the ai-guidance +
  dashboard parity gates so doc-sync is one entry point.
- **Interface doc-sync now covers config keys, MCP tools, and HTTP endpoints.**
  `dump-interface --include-endpoints` adds live FastAPI routes to the JSON
  snapshot; MCP tools gain a canonical generated list; config keys validate
  against the unified CLI+server schema and endpoints against the
  project-server + dashboard route tables; referential scans skip CHANGELOG.md.
- **Interface doc-sync now covers query modes and skills.** The deterministic
  `sync-docs` gate validates the `query --mode` choices and the `skills:`
  frontmatter in command docs against live code, command-doc flags tables are
  machine-owned `GENERATED:flags` blocks the generator creates and refreshes, and
  a single-pair command rename is detected and applied via a confirm-gated
  `git mv` (the `--check` path used by CI only reports, never moves).

### Fixed
- **CI doc gate no longer false-fails on the squashed `main` mirror.**
  `lint:docs-gates-ci` (run by the publish + PR-QA workflows) dropped the
  git-history-based `lint:doc-freshness` step: CI only ever sees the
  one-commit-per-release `main`, where every doc's content-change date collapses
  to the release commit and trips freshness regardless of fetch-depth. Freshness
  still runs in `task before-push` on the real `stable` history.
- **doc-sync's wrapped dashboard-parity gate no longer breaks CI.** The plan-4
  "one entry point" wrap ran the dashboard-parity pytest unconditionally, but
  that gate needs the dashboard's Python 3.12 venv which the server+cli CI jobs
  never install; it now skips when that env is absent and still runs in
  `task before-push`.
- **doc-sync endpoints checker no longer false-flags dashboard routes in CI.**
  When the dashboard package is not installed the snapshot has no `/dashboard`
  routes, so the checker can't verify dashboard references; it now skips
  `/dashboard`-prefixed doc tokens in that case and still gates them when the
  dashboard is present (`task before-push`).

## [26.6.39] - 2026-06-13

### Added
- **Single-source AI guidance across plugin, MCP, and hook.** AI usage guidance
  now flows from one file (`brainpalace_cli/data/ai_guidance.md`, tiers
  NUDGE⊂CORE⊂FULL) via the new `brainpalace ai-guide` command — the plugin
  `SKILL.md` is generated from it, MCP serves CORE as `instructions=` plus an
  `ai_guide` tool, and the SessionStart hook is a thin shim with legacy fat hooks
  auto-migrating on `brainpalace start`. The `lint:ai-guidance-parity` gate (in
  `task before-push`) fails on any surface drifting from the source.
- **Dashboard read-only toggle beside Stop.** The instance action bar (visible on
  the Status page) now has a one-click read-only switch that writes the sparse
  `server.read_only` override and restarts the instance, so the provider kill
  switch no longer needs the Config tab or the CLI.

### Fixed
- **Indexing no longer falsely fails on added empty files.** A watcher run that
  only adds zero-chunk files (e.g. empty `__init__.py`) leaves the store size
  flat, which `_verify_collection_delta` mis-flagged as
  `Verification failed: No chunks found in vector store`. Added files with no
  store shrinkage now verify as a valid zero-delta run.
- **Zero-chunk files no longer churn the watcher forever.** A loaded file that
  chunks to nothing (e.g. an empty `__init__.py`) was never written to the
  manifest, so every scan re-classified it as "added" and re-indexed it — a
  steady stream of watch jobs that created 0 chunks. Such files now get a
  manifest record with empty `chunk_ids`, so they read as "unchanged" on the
  next run.

### Changed
- **`configuring-brainpalace` skill slimmed to a router (793 → 587 lines).**
  Provider-config methods/profiles, the two GraphRAG env blocks, the inline
  troubleshooting tables, and the cache deep-dive were de-duplicated against the
  four reference guides they already cover; unique content (wizard question set,
  opt-in optional-dep rule, BM25 language config, read-only kill switch) stays
  inline. Fixed three stale commands in `references/provider-configuration.md`
  (`verify`/`test-embedding`/`test-summarize` → `brainpalace doctor`).
- **setuptools `<81` cap lifted — `pkg_resources` crash root cause removed.** The
  only runtime dep that hard-imported the (setuptools-81-removed) `pkg_resources`
  at module load was `stopwordsiso`, forcing a `setuptools >=65,<81` pin. The
  stopword dataset is now vendored verbatim
  (`indexing/text_analysis/vendor/stopwords-iso.json`, MIT) and `stopwordsiso`
  dropped, so the pin relaxes to `>=65` and setuptools 81+ no longer crashes
  indexing/keyword search.
- **Guided setup stops everything first.** `scripts/setup.sh` now asks up front
  to stop all running BrainPalace servers + the dashboard before touching the
  pipx venv, avoiding a live old-venv server clashing with the reinstall.
- **Setup no longer installs the Claude Code plugin from the CLI.** Driving
  `claude plugins …` from the script could hang on its process scan; the step now
  points users to install the plugin from inside Claude Code (`/plugin`) instead.
- **Config wizard flags summarization-OFF in red.** "Chat-session summarization is
  OFF" is now styled red so the user notices chat summaries are disabled.
- **Lemmatization prompt names the supported languages.** The BM25 lemma question
  now appends the lemma-capable languages (currently Croatian/Serbian), read live
  from the server's analyzer registry (`lemma_language_label`) rather than a
  hardcoded list, so it can't drift as languages are added.

## [26.6.38] - 2026-06-12

### Added
- **Automatic vector-store compaction.** Collection recreations strand dead rows
  in `chroma.sqlite3` that can balloon to several copies of the index, so a
  startup whose self-heal verifies the index complete now compacts heavy bloat
  away — live collections copied to a fresh persist dir (no re-embed), verified,
  atomically swapped, audited in `compact-events.jsonl`. Threshold-gated, so
  healthy stores pay nothing.
- **Manifest hardening — drop-after-verify.** Self-heal now marks
  not-fully-recovered files `pending_reindex` instead of deleting their manifest
  records, keeping the record and surviving chunk ids while the eviction diff
  forces a reindex regardless of mtime. The record is replaced only after the
  add-then-swap upsert lands, so a crash in the window loses nothing and retries
  on every start.

### Fixed
- **Stale git-history jobs are no longer replayed as folder reindexes.** The
  crash-recovery re-enqueue rebuilt an `IndexRequest` from a `git_history` job
  record — which carries `folder_path=<repo root>` and the `include_code=False`
  field default — running a documents-only index that evicted every code chunk
  as "deleted". Only `documents` jobs are re-enqueue candidates now.
- **Out-of-scope files are no longer treated as deletions.** An incremental
  index that didn't load a prior-manifest file (e.g. `include_code=False` over
  a code-indexed folder, a changed exclude pattern) only evicts its chunks when
  the file is also gone from disk; files still on disk keep their chunks and
  manifest record.
- **The per-job embedding token budget counts only cache misses.** Cached
  chunks cost no provider call, so a self-heal/recovery reindex whose
  embeddings sit in the embedding cache is no longer blocked by
  `BudgetExceededError` over its raw token size.
- **Self-heal's wanted git scope now mirrors the git indexer.** It wanted
  `rev-list --all` while the indexer walks HEAD with the monorepo path scope,
  so commits reachable only from other branches showed as phantom
  "N chunk(s) need re-embed" residue forever. Deep-clean's keep-set stays
  `--all` (never deletes chunks of commits alive on any ref).

### Added
- **Read-only mode** (`server.read_only` / `BRAINPALACE_READ_ONLY`): master
  provider kill switch that disables embedding, summarization and remote rerank
  — indexing jobs end `skipped` (zero deletes), startup self-heal recovers from
  cache only and skips destructive cleanup, and vector/hybrid/multi queries fall
  back to BM25. Toggle via `brainpalace read-only on|off|status` or the dashboard
  Config toggle; prevents the offline self-heal data-loss cascade.
- **Dashboard surfaces read-only + self-heal.** The per-instance Status page
  shows a read-only banner plus Read-Only, Self-Heal and Index-Health rows
  (parity with `brainpalace status`).

### Changed
- **Self-heal status no longer cries "INCOMPLETE" for the read-only skip.** When
  stage 2 is skipped *because* the server is read-only, `brainpalace status` and
  the dashboard now show a healthy "recovered X/Y … stage 2 skipped — read-only
  (no deletes)" instead of the alarming "⚠ INCOMPLETE … fix + restart" (that copy
  is reserved for a genuine failed/partial recovery).
- **Dashboard log-alerts wrap instead of truncating** so long self-heal / error
  lines are fully readable.

## [26.6.37] - 2026-06-12

### Fixed
- **Lost vector chunks now actually recover at startup — from cached vectors, with no re-embedding.** The new `chunk_recovery` plane restores each lost chunk (code/doc **and git**) by reading its text from the stranded *dead* Chroma segments and its vector from the embedding cache (`SHA256(text)`), then upserting it back with zero provider calls — replacing the old self-heal that only re-indexed and was a no-op on the real backend. It restores the latest stranded copy per chunk id and rebuilds the lexical BM25 index (code/doc) so keyword search finds them.
- **Self-heal is now recover-first, destroy-last, with a hard gate.** Stage 1 recovers (no API); only if it fully succeeds does stage 2 run — drop the manifest records of files that are *not fully recovered* (so they reindex like any unindexed file, after `deep_clean`), then `deep_clean`. A failed or partial recovery keeps stage 2 CLOSED, so the index is never dropped or purged on top of an unrecovered store.
- **Self-heal result is surfaced.** A prominent startup notification fires only when recovery actually runs (or is blocked/incomplete), and `brainpalace status` shows the last result (restored / dropped / residue, or an INCOMPLETE warning). The healthy-start probe is also cheaper now — a `count()` pre-check skips the per-id scan when nothing is missing.
- **`pkg_resources` crash no longer returns above setuptools 81.** The bare `setuptools >= 65` pin resolved to setuptools 82 on the pip-installed CLI venv — and setuptools **81 removed the vendored `pkg_resources`**, re-breaking code indexing and keyword search with "No module named 'pkg_resources'". Capped to `>=65,<81` until the `pkg_resources` import is dropped.

## [26.6.36] - 2026-06-12

### Changed
- **Clearer setup-wizard session prompts + a safer post-install default.** The `config wizard` rewords the embed question (says it goes through your embedding provider, and is independent of chat summarization) and the archive question (stored locally in `.brainpalace/`, never leaves the machine), and the lemmatization prompt now states the download size (~65 MB); `setup.sh`'s "Set up and index a project now?" now defaults to No.

### Fixed
- **Code indexing no longer crashes on a missing `pkg_resources`.** `setuptools` (which provides `pkg_resources`, imported transitively at index time by tree-sitter) is now a declared server dependency, so indexing can't die with "No module named 'pkg_resources'" on Python 3.12 environments that ship without setuptools.
- **Index self-healing is now a layered procedure that runs at startup and on a periodic heartbeat.** Two independent planes keep the index correct against the data-loss failure modes from a recent incident. The *vector plane* (`heal_if_corrupt`, startup + every ~3 min, for both the code and memory collections) detects a corrupt/bloated HNSW — the on-disk approximate-search index — from its metadata and **rebuilds it from the intact embeddings in ChromaDB's SQLite, with no re-embedding**; the *bookkeeping plane* (startup + every ~30 min) reconciles the per-file manifests in `.brainpalace/manifests/` against what the store actually holds.
- **The bookkeeping plane both recovers and cleans, each source type against its own source of truth.** *Recover:* chunk IDs a manifest claims but the store has lost (e.g. an HNSW that shed live vectors) are dropped from the manifest so those files re-index next run — it never deletes store data. *Clean (existence-based, never by age):* `code`/`doc` chunks no manifest references are removed (with whole vanished folders), `session_turn` chunks are removed when their source transcript is gone from disk, and `git_commit` chunks are removed when their commit is no longer reachable in the repo (`git rev-list --all`, so a reset/rebase/squash reaps them) — each cleaner is skipped while indexing runs and refuses to act when its baseline can't be verified (no manifest union, missing archive dir, or unresolvable repo).
- **A self-heal that sheds vectors is now loud and auditable, not a buried log line.** When the HNSW rebuild keeps far fewer vectors than the index physically held, the drop is recorded to `.brainpalace/heal-events.jsonl` and surfaced as an "Index Health" warning in `brainpalace status`, telling you to re-index to recover.
- **A second server can no longer attach to a project that already has a live one.** On startup the server probes the project's recorded `runtime.json` endpoint and refuses (instead of clearing the lock) when a healthy server is already serving that project, and `is_stale` now treats a lock as stale only when the server is both dead and unreachable — closing the duplicate-server path that corrupted the embedded Chroma index.
- **Re-indexing a changed file no longer risks losing it on a crash.** Incremental indexing now adds the new chunks first and deletes the file's old chunks only after the new ones are safely stored (atomic add-then-swap), so an interruption mid-reindex leaves the old chunks intact instead of a gap; deleted-file chunks are still evicted immediately.

## [26.6.35] - 2026-06-12

### Changed
- **Two-stage reranking is now off by default, and its local model is an opt-in extra instead of a ~2.8 GB tax on every install.** `sentence-transformers`/PyTorch moved to a `reranker-local` extra installed only when you enable the local reranker (via `init`/`config wizard`, which now default the question to no and warn about the download); a query with reranking on but the extra absent falls back to stage-1 with an actionable warning. For a torch-free reranker, set `reranker.provider=ollama` instead.

### Fixed
- **Installing/updating no longer backtracks for minutes.** The installer (`scripts/install.sh` and the plugin `brainpalace-install` commands) now pins all three packages to the target version, and the publish workflow ships the dashboard's CLI dependency as a caret instead of an exact `==`, so pip/uv/Poetry resolve in one shot. The installer fix applies immediately; the caret takes effect for releases after 26.6.34.

## [26.6.34] - 2026-06-11

### Added
- **Dashboard time/date display preferences.** The Settings tab gained a clock-format (24-hour default / 12-hour) and a display date-format (`dd.mm.yyyy` default / `mm.dd.yyyy` / `yyyy-mm-dd`) selector, stored in the `dashboard:` block (`time_format`/`date_format`) and applied everywhere the SPA renders an absolute time or date. Requires the reshipped `static/assets` bundle. (dashboard #9)
- **`config wizard --global` asks for the web-dashboard settings.** It now prompts for `dashboard.autostart` (default ON — whether `brainpalace start` also launches the dashboard) and `dashboard.port` (default 8787), writing them to the `dashboard:` block; `dashboard` is now a recognised top-level config key. Per-project `init` does not ask these. (dashboard #5)
- **Dashboard fleet lists every project ever started, and self-prunes deleted ones.** `brainpalace start` records each project in a shared durable store (`known_projects.json`), so a project stays listed and Start-able after its server stops; reads prune any project whose directory was deleted. The same store backs the guided `uninstall` teardown, replacing the dashboard's private `dashboard_known.json`. (dashboard #3)
- **Dashboard session archive shows a readable title.** `/sessions/archive` rows carry a `title` (the first line of the session's first user prompt), rendered as the Session label with the id beneath. Only that first line is exposed — full transcript content is still never returned. (#2)
- **Git-history indexing is now a visible queue job.** It previously ran outside the job queue, so its chunks never appeared in `brainpalace jobs`. Git indexing now enqueues a `job_type="git_history"` job (repo-scoped dedupe collapses boot + on-demand into one; a no-new-commits reindex marks DONE); document indexing is unchanged. (#15)
- **Install/init question parity + opt-in optional-dep installs.** `bp install` (`config wizard`) and `bp init` now ask the same project-config-backed set, with `init` re-asking the per-project reranker behind an inherited-override gate. A feature whose "yes" needs an optional server extra (GraphRAG → `langextract`, BM25 lemma → `simplemma`) installs it on yes only; deps are never auto-installed just because a feature is default-ON, and `brainpalace doctor` reports extra status for enabled features. (#10/#12/#13/#14/#16)

### Fixed
- **Dashboard latency p50/p95 tooltip showed many decimals.** Hovering the "Latency p50 / p95" chart now rounds each value to a whole number and appends `ms`, matching the stat cards above it. (dashboard #8)
- **Dashboard Documents tab showed "0 B" for files that have chunks.** Records predating the `size_bytes` field (and unchanged files never re-embedded) carry `size_bytes=0`; `GET /index/documents` now back-fills the size by stat-ing the live file when stored size is 0. The tab also stops truncating the file path mid-string — it now wraps. (#1)
- **Removing a folder could evict chunks another folder still owned.** Removal deleted *every* chunk_id of the removed folder, dropping chunks a nested/overlapping folder still referenced. It now deletes only chunks unique to the removed folder; shared chunks survive and true orphans are reaped by startup reconcile.
- **`brainpalace init` leaked server INFO logs and trailing boilerplate.** The in-process estimate/preflight emitted raw server-module logs; those now run under a `brainpalace_server` logger set to WARNING. The trailing "Next steps:" block is dropped on a fully-successful run (it appears only when a real action remains).
- **CLI commands could silently target a *different* project's server.** When discovery couldn't validate the owning project's live server, `get_server_url` fell through to a default `:8000` — often another project's server. It now raises `ServerNotReachableError` instead of guessing (with `doctor` opting out so it still diagnoses a down server).
- **Dashboard "remove folder" failed with a 422.** The frontend sent `{"path": …}` but the server expects `{"folder_path": …}`. Fixed the frontend call and hardened the dashboard proxy to normalize `path` → `folder_path`, so an older bundled asset also works.
- **Install/update could fetch the *previous* version right after a release.** `setup.sh` invoked `install.sh` unpinned, and every path resolved "latest" through a stale package-manager index cache. Now setup.sh passes the detected version and all install/upgrade paths bypass the cache (mirrored in the plugin `brainpalace-install` command).
- **Dashboard instances accumulated and survived `update`.** A lost/overwritten pidfile let the next launch port-walk and spawn a second dashboard, and `stop`/`update` only killed the one tracked pid. The dashboard now reaps orphans by process scan; `update` reaps stray servers and dashboards across install surfaces before restarting.

### Changed
- **Sessions tab: the reconcile-sweep status moved to the Session archive card.** The "Watcher" row (the periodic `session_reconciler` sweep) drives the archive copy, so it now reads "Copy sweep: running/idle" under Session archive; the index card is renamed "Session summarization & indexing" and keeps only chunk + memory counts. (dashboard #10)
- **Config tab: the "Provider connectivity" check now sits below all provider settings** (previously above the form), so it validates the values shown above it. (dashboard #4)
- **Queries: top-query rows are now clickable** and open the same per-query detail drawer as a history row. `GET .../queries/stats` `top_queries` entries gained a `last_id` (the query's most recent occurrence) for the drawer. (dashboard #6)
- **The per-instance "Documents" tab is renamed "Files"** (nav label + heading); the route path is unchanged. (dashboard #7)
- **Dashboard config UI: inheritance is now legible.** The inherited/default value renders below the control as a high-contrast chip; inherited boolean toggles render muted (still clickable, flipping promotes to a local override); and the reranker section's help explains the two-stage retrieval mechanism. Requires the reshipped `static/assets` bundle.
- **`brainpalace init` estimates token cost *before* the final gate, and flags a missing plugin on the summarize question.** After writing the sparse config it asks "Estimate token usage first?", runs the git-aware estimate (`proceed / change options / cancel`), then shows the `init will: …` summary as the last confirmation. The "Summarize chat sessions?" prompt warns in yellow when the Claude Code plugin is absent.
- **`brainpalace update` is now stop-all → upgrade → restart-and-verify.** One consent prompt names every live instance; on confirm all are stopped, the upgrade runs, then each is restarted with a ✓/✗ health check — removing the silent-stale-version trap. A failed upgrade tells the user loudly that nothing is running; `--no-restart` keeps the upgrade-only path.

### Docs
- **Setup-surface parity: plugin + MCP docs mirror the unified init/install question set + opt-in optional-dep rule.** The plugin setup/config/install commands, the `setup-assistant` agent, the `configuring-brainpalace` skill, and `docs/MCP_SETUP.md` now describe the shared questions, the inherited-override gate, and the rule that enabling an optional-dep feature installs the extra rather than auto-installing for a merely default-ON feature.

## [26.6.33] - 2026-06-11

### Added
- **Dashboard Retrieval Explorer.** The Queries composer can run one query across bm25/vector/hybrid/graph side-by-side with per-result score chips and shared-chunk highlighting, plus a per-request reranker override (`QueryRequest.rerank`).
- **Dashboard query analytics.** The Queries tab aggregates the query log (top queries, latency p50/p95 trend, mode distribution, zero-result queries) via the new `GET /query/stats`.
- **Dashboard Documents tab.** Browse indexed files per folder with chunk counts and open any file's chunks (text + metadata) via the read-only `GET /index/documents` and `GET /index/documents/chunks`.
- **Dashboard Cache tab.** Embedding-cache hit-rate trend (`GET /index/cache/history`) and an estimated spend/savings panel (`GET /index/cache/economics`, static price table — estimates only).
- **Dashboard session-memory browser.** Archived-session inventory (`GET /sessions/archive`, metadata only), a Decision browser with temporal supersession timeline (`GET /sessions/decisions`, `GET /sessions/timeline`), and curated-memory creation.
- **Dashboard graph browser.** Search seed entities and explore the knowledge graph on a WebGL canvas (sigma.js, lazy-loaded) with click-to-expand neighbors, via `GET /graph/nodes` and `GET /graph/neighbors`.
- **Dashboard polish.** One-click provider connectivity test (`POST /health/providers/test`), a log alerts strip, a Cmd/Ctrl+K command palette, and a cross-instance effective-config diff.

### Changed
- **SessionStart reminder now documents the `query --json` schema.** The plugin hook + `install-session-hooks` template include the per-result keys (`text`/`source`/`score`/`chunk_id`), the failure shape, and the "never append `2>/dev/null`" rule, so agents parse output correctly. Both hook copies updated in lockstep.
- **`using-brainpalace` skill gains a "Parsing `--json` Output" section** (result keys, error shape, canonical parse snippet, `2>/dev/null` ban) — the push channel for non-Claude runtimes via `brainpalace install-agent`.
- **`--json` server-error payload now includes a `hint` field** teaching the success schema, since failure time is the only contact point for raw CLI consumers that never read `--help`.

## [26.6.32] - 2026-06-10

### Added
- **Layered config resolution — `code < global < project`.** The server merges the global XDG config under the project config per key (env still wins on top), and the project file is sparse — `init` writes only values that diverge from the inherited one. New `brainpalace config unset <dotpath>` removes a project key so it inherits again, surfaced in the dashboard config form as a provenance badge + unset control (`POST /config/unset`).
- **Per-job embedding token budget guard** (`indexing.max_embed_tokens_per_job`, default 300k). Jobs over budget are blocked with a clear CLI error; `force_budget: true` bypasses and `limit=0` disables it. Applied in the document, git-history, and session index pipelines.
- **Folder-add provenance** (trigger source) is recorded and logged.
- **Server-less in-process token estimate** (`estimate_tokens_local`) so `init` can show the cost estimate before starting a server or writing index data.

### Fixed
- **Reranking no longer returns HTTP 500 for ordinary `top_k`.** The stage-1 over-fetch rebuilt a public `QueryRequest`, tripping its `top_k ≤ 50` validator (any `top_k ≥ 6` at the default multiplier). Stage-1 now uses `model_copy`, bypassing the public ceiling while staying bounded by `RERANKER_MAX_CANDIDATES`.
- **`brainpalace query --help` documents the `--json` output schema** — keys are `text`/`source`/`score`/`chunk_id`, and on failure `--json` emits `{"error": …}` (no `results`) and exits non-zero, so consumers must check the exit code.
- **Reap orphan server processes.** `brainpalace stop --all` and `doctor --reap` kill running server processes no live registry entry references; `start` reuses a project's live registry server instead of spawning a duplicate on a climbed port.
- **`init` runs the token estimate before writing index data;** cancelling rolls back the `.brainpalace` created this run. A pre-existing `.brainpalace` prompts delete / keep / cancel up front, and the estimate is asked exactly once.
- **Include git-history and session embedding in the pre-index token estimate.**
- **Prune folder records for deleted paths on startup;** add `brainpalace folders prune`.
- **Scope git-history indexing to the project subdir in monorepos** (was embedding the entire monorepo history).
- **Job "Files" metric showed `0 / 0` for code-only jobs.** The real document count is now reported on the 10% "Chunking documents" tick, so `files_total` is set for every run regardless of doc/code mix.
- **`brainpalace update` now prints the dashboard URL panel after restarting** (parity with `start` / `dashboard start`); previously the restart was silent about the URL.

---

## [26.6.31] - 2026-06-09

### Added
- **Pre-index embedding-token estimate.** `brainpalace index <path> --estimate` prints an approximate embedding-token count without indexing, using the exact file-selection rules of a real index (new `POST /index/estimate`). `init` offers it before the first index, where you can proceed, toggle code/docs scope and re-estimate, or skip; new `--include-code/--no-code` threads that choice through both the estimate and the index.
- **Dashboard instance detail header gains inline Start / Stop / Restart (+ Open)** for the selected instance, so bouncing the instance you're viewing no longer detours through Server → Instances.
- **Per-job chunk deltas.** Jobs now record `chunks_added` / `chunks_removed`; the Jobs table gains **+Chunks** / **−Chunks** and a computed **Duration** column, and the job-detail drawer shows added/removed plus a distinct "Index total".

### Changed
- **Jobs table merges Status and Progress into one column** — the badge always, with an inline progress bar only while a job is active.

### Fixed
- **Job "Files" count no longer always reads `100 / 100`.** `JobProgress` stores the phase-weighted percent in a dedicated `percent` field, decoupled from `files_processed` / `files_total`, which now carry real document counts.
- **Job detail no longer shows the same number for "Chunks" and "Chunks created"** — the per-job insert delta is computed from the store count before/after plus eviction, distinct from index-wide `total_chunks`.
- **Dashboard "update available" banner no longer goes stale after an upgrade.** `update_check` caches only the PyPI `latest` (6h TTL) and reads the installed version live each poll, so the banner self-clears the moment installed ≥ latest.

### Changed
- **`brainpalace update` prints a pre-flight notice** listing the running servers / dashboard before the upgrade (they keep serving old code until restarted, which still happens after the upgrade on confirmation).

---

## [26.6.30] - 2026-06-08

### Added
- **Server self-registration.** A running server writes its own `runtime.json` and global `registry.json` entry (learned from the bound socket) regardless of launch path and re-asserts every 180s — fixing servers being invisible to the dashboard.
- **Server-side self-heal heartbeat.** Restarts a dead file watcher or job worker, rebuilds a corrupt vector index (crash-safe file-only check), and relaunches the dashboard if down.
- **Dashboard config save guards against data-incompatible changes.** Editing the embedding provider/model, storage backend, or graph store type while data is indexed is blocked with a "Save & reindex now" action (new read-only `GET /index/fingerprint`).
- **Per-field help across Storage, GraphRAG, Git Indexing, Reranker, and Session Extraction,** plus section descriptions distinguishing Session Extraction (curated summary) from Session Indexing (archive/embedding).

### Changed
- **Single locked writer for `registry.json`** (server `registry.py`); CLI `update_registry` delegates to it (no more lockless writes).
- **One `build_server_command`** builds the uvicorn argv for all CLI/MCP launch paths.
- **One `render_dashboard_url`** renders the dashboard box for `init`/`start`/`dashboard`.

### Fixed
- **`config` wizard now defaults graphrag `store_type` to `sqlite`** (persistent, temporal) instead of ephemeral `simple`, matching the server and dashboard defaults.

## [26.6.29] - 2026-06-08

### Added
- **`brainpalace update` restarts running servers + the dashboard.** After a successful upgrade it detects every running per-project server and the dashboard and offers to restart them (default yes; `--yes` auto-confirms; `--no-restart` keeps the old behavior). Each server is bounced with `--no-dashboard` so the dashboard restarts exactly once.

## [26.6.28] - 2026-06-07

### Added
- **Dashboard update notification.** A top-of-app banner appears when a newer `brainpalace-cli` is on PyPI, via the best-effort `GET /dashboard/api/settings/update-check` (6h TTL, degrades silently). Informational only — no automatic upgrade.
- **Dashboard job detail.** Jobs-tab rows are now clickable and open a drawer showing documents/chunks indexed, duration, files processed, and the eviction breakdown, via the existing `/index/jobs/{job_id}`.

### Changed
- **`brainpalace init` surfaces the dashboard URL.** Init now extracts the URL from its `start --json` step and shows it in a pink panel (opening a browser when interactive), instead of suppressing it.
- **`brainpalace init` prompt defaults** are now: summarize chat sessions = N, index git commit history = Y, commits-back-to-index = 5000.
- **Dashboard config pages load again.** `ui_schema` had `visible_when.equals` as a boolean for `bm25.detect`; the SPA requires a string, which broke `/dashboard/config` and `/dashboard/global-config`.
- **Dashboard queries default window is now 24h** (was 7d).

## [26.6.27] - 2026-06-07

### Changed
- **Config validation hardening (Phase 5).** The shared `validate_config_dict` now enforces numeric ranges, not just types, so bad values are rejected at save instead of at server start — ports 1–65535, `bm25.detect_min_confidence` 0.0–1.0, and count/duration fields ≥ 0. Deliberately omitted as false-positive-prone: hard provider/model compatibility and required-`base_url`.
- **Dashboard perf + clearer labels (Phase 4).** Dropped repaint-storming `backdrop-blur` from the base panel/sidebar, honored `prefers-reduced-motion`, and memo'd the recharts components so interval polling stops re-running expensive passes. Relabels: high-contrast Enabled/Disabled toggle text (#9), `bm25.detect` → "Auto-detect language (per document)" with `bm25.language` reframed as the default/fallback (#12), and `session_indexing.sessions_dir` → "Transcript source dir (override)" (#13).

### Added
- **Large-file re-embed guard (anti-churn).** A large, frequently-changing file (minified bundles, build artifacts) used to be fully re-embedded on every change, causing runaway cost. A per-file re-embed cooldown defers large changed files within `reembed_cooldown_seconds` (keeping their chunks), a `skip_minified` heuristic drops minified files at load time, and a new `indexing:` config block exposes the knobs (`reembed_cooldown_seconds`, `big_file_chunks`, `max_file_bytes_throttle`, `skip_minified`) with env overrides.
- **Provider-driven config forms + one canonical model map.** New `providers.py` is the single source of truth per kind/provider (`models`, `needs_base_url`, `default_api_key_env`); `GET /schema` exposes it so the dashboard reshapes embedding/summarization/reranker forms when the provider changes. The CLI wizard suggestions and README provider tables now derive from it, and per-field help was added.
- **Dashboard: all three config scopes are now editable, clearly separated.** Global config gets a dedicated tab on the Server page (`GET/PATCH /dashboard/api/global-config`); the per-project runtime bind (`config.json`: host/port-range/auto_port) gets a per-instance Runtime tab (`GET/PATCH .../runtime-config`, restart-aware). Previously-hidden per-project fields (`*.params`, `git_indexing.path_filter`, `session_indexing.archive`) are now surfaced.
- **`brainpalace start` brings up the web dashboard and prints its URL.** On Python 3.12+ it ensures the singleton dashboard is running and prints a clickable URL, opening a browser only when it actually launches it (never under `--json`/CI). Opt out per-run with `--no-dashboard` or persistently with `dashboard.autostart: false`; the launch is best-effort and never fails `start`.

## [26.6.26] - 2026-06-07

The **web dashboard** lands — a standalone browser control plane for every
BrainPalace project server — published to PyPI and **included with the CLI
automatically on Python 3.12+**.

### Packaging
- **`brainpalace-dashboard` is now published to PyPI and bundled with the CLI.** It is a third lockstep package carried as a regular CLI dependency with a `python >= 3.12` marker, so `pipx install brainpalace` pulls it in on 3.12+ and skips it on 3.10/3.11 (not an opt-in extra). The release workflow gained a `publish-dashboard` job and the version guard now covers all three `pyproject.toml` versions.

### Changed
- **Reranking is now ON by default and config-controllable.** The local cross-encoder re-scores top candidates for finer relevance — no API/token cost, a little latency and a one-time model download. New `reranker.enabled` (default `true`) is the per-project switch (`init` writes it, `--reranking/--no-reranking`, dashboard toggle); `ENABLE_RERANKING` still overrides.

### Added
- **Dashboard: config defaults are surfaced.** Every control shows its effective default next to the label, so an omitted setting no longer looks broken; the all-hidden runtime sections (API/Server/Project) are no longer rendered as empty headers.
- **Dashboard: Server and Instance are now separate pages.** The rail has a Server (control-plane) entry above the instance list; selecting Server shows only server tabs and selecting an instance shows only its tabs.
- **Dashboard: Status tab mirrors `brainpalace status` in full** — version, code+doc documents/chunks, indexing state, folders, watcher, sessions, cache, graph, LSP, git, and BM25 language/engine (adds a `/health` proxy for the version).
- **Dashboard: control-plane "Settings" tab.** Edits the dashboard's own config (`host`/`port`/`poll_s`/`token` in the `dashboard:` block) — the token is write-only — via `GET`/`PATCH /dashboard/api/settings`.
- **Dashboard: per-instance "Status" tab + grouped tabs.** A new instance-scoped Status view, with the tab bar visually separating Fleet tabs from the per-instance group.
- **Dashboard: confirmation on every mutating action.** Config Save / Save+Restart, instance Start, and "mark memory obsolete" now prompt, joining the already-confirmed actions.

### Fixed
- **`brainpalace dashboard start` now backgrounds properly.** The child now starts in its own session with output redirected to `<XDG_STATE>/dashboard.log`, so the prompt returns immediately (`--foreground` runs attached).
- **Graph/Sessions/Overview no longer error on real instances.** The status schema typed `indexed_folders` as a number, but the server returns the list; it now accepts the list and derives the count.
- **Logs tab degrades gracefully** when a server predates `/health/logs` or has no log file — a clear note instead of a hard "Not Found".
- **`brainpalace dashboard` command + web control plane.** A standalone FastAPI/React dashboard manages every project server from one browser tab (instances, config, stats, jobs, cache, graph, sessions, logs, history) via its own port scan (8787→8887) and pidfile. An optional bearer token (`dashboard.token`) guards `/dashboard/api/**`; see [DASHBOARD](DASHBOARD.md).
- **Server query history (SQLite) + dashboard Queries tab.** Every successful query is recorded to `.brainpalace/query_log.db` (ON by default, 7-day retention, `QUERY_LOG_ENABLED=false` kill switch), with new `GET /query/history`, `/query/history/{qid}`, and `/health/logs` endpoints proxied by the dashboard.
- **Dashboard parity gate.** New `task lint:dashboard-parity` (in `task before-push`) fails when a config option, CLI command, or endpoint is added without being surfaced in the dashboard or allowlisted; it imports the live schema/Click group/FastAPI app and diffs against checked-in coverage maps.
- **Dashboard E2E + polish.** A Playwright suite drives the full lifecycle plus an axe-core accessibility check; every tab gained loading/empty/error states, a Queries "New query" composer, and accessibility fixes. Fleet liveness rides a single SSE stream with bounded refresh intervals (documented in `docs/DASHBOARD.md`).
- **Config validation + dashboard Config save on real projects.** `config_schema` now recognizes the `bm25`, `git_indexing`, `session_indexing`, `session_extraction` sections (and `graphrag.store_type: sqlite`) that real configs carry, fixing the Config tab failing on every project with these sections. The editor is also tolerant of unknown sections and blocks a save only on errors in fields it actually changes.

## [26.6.25] - 2026-06-07

### Changed
- **Git history indexing now indexes the full history by default.** `git_indexing.depth` changed from `1000` to `0` (no cap) — the silent 1000-commit cap surprised users on larger repos. Set a positive `depth` to bound the first pass on very large repos.
- **`brainpalace init` now asks how many commits back to index** when you opt into git history (default `0` = unlimited), writing `git_indexing.depth`.

## [26.6.24] - 2026-06-06

### Fixed
- **Git history index never indexed any commits (`status` showed `0 commits`).** The chunker stored changed files as a metadata list, which ChromaDB rejects, failing the whole boot-index upsert. Paths are now a newline-joined string plus a scalar `files_changed_count`.
- **Vector (semantic) search returned almost nothing.** Long-lived collections could be stuck on ChromaDB's `l2` default while the query layer scores cosine, mapping distances to negative similarity that gets filtered out. The self-heal now detects a non-cosine index behaviorally and rebuilds it onto cosine from SQLite — no re-embedding.
- **Self-heal left the old vector segment dir on disk.** Rebuilding drops the segments row but not the folder, leaking a stale index; the heal now sweeps orphaned segment directories after a rebuild.
- **Server segfaulted on startup against a bloated/corrupt vector index.** An accumulated HNSW index triggered a native resize segfault with no traceback, crash-looping the server. `VectorStoreManager` now self-heals before any write — a crash-safe disk read of the element counter rebuilds a compact index from intact SQLite, no re-embedding.
- **`install.sh --local` failed or silently ran the PyPI server.** The `pipx inject` collided with the `./brainpalace-cli` dir or was skipped without `--force`. The injector now runs from a neutral CWD with `--force` and an absolute `--local` path.
- **Duplicate server for the same project (double-counted index).** A live-but-busy server missing one `/health` probe was treated as stale and replaced by a twin; `start` now retries the probe and refuses rather than launching over a live process, no longer unlinks the held `flock`, and `launch_server` probes the port range for a healthy same-`project_root` server.
- **Folder `chunk_count` grew forever and never self-healed.** The chunk-id set was a blind union of old + new ids; it is now derived from the authoritative per-file manifest, so the count shrinks on delete and converges on every incremental re-index.
- **Server now self-heals manifest/store drift on every start.** A startup reconcile recomputes each folder's `chunk_count` from the manifest and purges store chunks the manifest no longer references — pure bookkeeping, no reindex/re-embed, never blocks startup.

---

## [26.6.23] - 2026-06-06

### Added
- **Nested BrainPalace projects are auto-excluded from the outer index.** Any subfolder with its own `.brainpalace/` is pruned (whole subtree) from the outer project's discovery and watching, checked live on every walk so deleting the nested `.brainpalace/` re-includes it.
- **`brainpalace init --migrate-graph-store / --no-migrate-graph-store`** plus an interactive prompt (default yes) to upgrade an initialized project from the legacy `simple` graph store to `sqlite` (the graph replays on next start; JSON kept for rollback).

### Fixed
- **Graph status reported `0 entities` at cold start.** The lazy graph store now hydrates entity/relationship counts from the persisted `graph_metadata.json`, so `status` reflects the on-disk size immediately after boot.
- **Re-init dropped interactive answers.** On an already-initialized project the git-history/summarize/embed answers are now persisted (previously ignored), and the result banner reads the true session state from `config.yaml`.

### Changed
- **`brainpalace init` prompt order:** the graph-store upgrade is asked with the other questions and shown in the `init will:` preview; mono-repo-root refusal happens before any prompt.

## [26.6.22] - 2026-06-06

### Added
- **`brainpalace init --git-history / --no-git-history`** plus an interactive prompt (default no) to index git commit history as searchable chunks; written to `git_indexing.enabled` only when enabled.
- **`git_indexing.path_filter`** config — limit git-history indexing to commits touching specific repo-relative paths (`git log -- <paths>`), for mono-repos where one `.git/` serves several projects.
- **`brainpalace init --migrate-graph-store / --no-migrate-graph-store`** plus an interactive prompt (default yes) to upgrade an initialized project from `simple` to `sqlite`.
- **`brainpalace status` rows:** LSP (enabled/disabled languages), Git Index (on + commit count / off), and the graph store type with a temporal-availability note.

### Changed
- **GraphRAG defaults flipped to on + persistent.** `ENABLE_GRAPH_INDEX` now defaults `true` and `GRAPH_STORE_TYPE` to `sqlite`; `init` writes `graphrag.store_type: sqlite`. Existing projects keep their configured `store_type` until they opt into the migration.
- **Gemini removed from CLI embedding providers** (the server has no Gemini embedding provider); Gemini remains a summarization provider.

### Documentation
- **Graph defaults corrected across all docs** (`ENABLE_GRAPH_INDEX: true`, `GRAPH_STORE_TYPE: sqlite`) in GRAPHRAG_GUIDE, CONFIGURATION, and the configuring-brainpalace skill.
- **`git_indexing.path_filter` documented** in CONFIGURATION.md and GIT_HISTORY.md.
- **Temporal/simple warning added** to GRAPHRAG_GUIDE.md — `store_type: simple` makes temporal validity unavailable; `sqlite` is now the default.
- **"Agent Brain" rename** — GIT_HISTORY.md uses the correct product name BrainPalace throughout.
- **Embedding provider tables corrected** to list only the real providers (OpenAI, Cohere, Ollama).
- **`kuzu` backend scrubbed from all docs,** replaced with `sqlite`/`SQLitePropertyGraphStore` (server retains a graceful `kuzu` → `simple` downgrade so old configs never crash).
- **`GRAPH_EXTRACTION_MODEL` standardized to short form** `claude-haiku-4-5`.
- **Gemini model IDs updated to the current generation** (default `gemini-3.1-flash-lite`, premium `gemini-3.5-flash`, pro `gemini-3.1-pro-preview`).

---

## [26.6.21] - 2026-06-05

### Fixed
- **CI quality gate: `TestSentenceTransformerWarmUp` tests no longer hit the network.** They now mock `_ensure_model_loaded` / `hf_hub_download`, fixing the v26.6.20 publish failure (the tests required a cached model only present on the developer machine).

---

## [26.6.20] - 2026-06-05

### Fixed
- **Fresh-folder `watch=auto` is now persisted at the start of indexing,** not only on clean completion, so a first index killed mid-tail no longer leaves a new folder unwatched. An explicit `--watch` flag always wins; a flagless re-index preserves the existing setting.
- **Indexing now honours `.git/info/exclude` and the global `core.excludesFile`** in addition to `.gitignore`, matching Git's precedence, so local-only excludes are no longer indexed (located via `--git-common-dir` for worktrees).
- **Indexing progress now advances through the whole pipeline** instead of sitting then jumping to 100% — persistence is throttled by percent-of-total, the bands are rebalanced, and the graph-build phase reports per-document progress.
- **`langextract not installed` is logged once per process** instead of once per document.
- **Project discovery now ignores an uninitialized `.brainpalace/` scaffold.** A stray `.brainpalace/` with no config/runtime files no longer shadows the real repo root; discovery requires an initialized `.brainpalace/` and otherwise walks up.

### Changed
- **`brainpalace status` splits documents and chunks into code vs doc counts** (`N (X code · Y docs)`), derived durably from manifests + the store's `source_type` filter so it survives a restart.
- **`brainpalace status` always shows session summarization as its own row** (`off` / coverage %), making clear it is independent of session embedding and raw archive.

### Deprecated
- **`BRAINPALACE_CHECKPOINT_INTERVAL` / `progress_checkpoint_interval` no longer affect progress cadence** — progress persistence is now percent-based (`PROGRESS_MIN_PERCENT`); the setting is accepted but ignored.

---

## [26.6.19] - 2026-06-05

### Changed
- **`brainpalace init` asks before embedding/summarizing chat sessions, and embedding is opt-in.** Interactive init prompts to summarize (free Haiku subagent) then to embed (billable) with plain-language explanations; a bare `init` and `--yes` keep embedding off (archive + summarize only). Use `--sessions` to opt in, `--no-extract` to skip summarization.
- **`brainpalace init` second-part output reflects real state.** The chat-summaries line branches on the resolved engine + plugin presence (warning and pointing to `install-agent` when absent), and the Done block names the real session-embedding cost with its provider — clarifying that billable embedding is independent of free summarization.
- **`brainpalace init` preview names the real provider per action.** Each data-out step is tagged with its destination (e.g. `embed chat sessions → OpenAI text-embedding-3-large`) instead of abstract billable/free; the summarize line is omitted when the plugin is absent.

### Fixed
- **A Claude Code marketplace clone no longer counts as an installed plugin.** The registry-missing fallback globbed a path that matched a marketplace clone; it now consults explicit install dirs only (mirrored in CLI and server).
- **An interactive init embed/summarize answer now wins over an XDG-inherited `session_indexing` block** — a prompt answer is treated as explicit, so declining writes `session_indexing.enabled: false` even when global sets it true.

---

## [26.6.18] - 2026-06-04

### Added
- **Opt-in time-driven session summarization (subagent path).** New `brainpalace drain-tick` + `/brainpalace-drain` let you opt into idle-time queue draining via a dedicated `claude --model haiku` + `/loop 5m` babysitter — mode-gated, single-drainer locked, self-terminating after 3 empty drains. No automatic trigger; default session behavior is unchanged.

### Changed
- **Archive copy is now a periodic sweep, and quiescence is configurable.** Sessions are copied every `session_archive.reconcile_seconds` (default 600s) by a reconciler instead of per-change, and the summarization idle gate is `session_extraction.quiescence_seconds` (default 1800s). Env overrides: `SESSION_ARCHIVE_RECONCILE_SECONDS`, `SESSION_QUIESCENCE_SECONDS`.
- **Session summarization is now archive-driven.** The free subagent path summarizes archived sessions that are new, grown, or late-copied (reading the archive, not `~/.claude`), gated by quiescence; the SessionEnd `extract-queue` is retired and a new `brainpalace session-path` resolves an archived transcript.
- **`brainpalace uninstall` groups every optional/manual leftover at the very end.** The marketplace-plugin notice now appears in the final "Remaining steps (optional / manual)" block alongside the package-uninstall and API-key reminders, instead of scrolling past mid-teardown.

---

## [26.6.17] - 2026-06-04

### Fixed
- **An interrupted index no longer leaves orphan chunks with a 0-document status.** The folder record + manifest are now persisted immediately after the chunk upsert (before the rebuildable BM25/graph tail), so an interrupt leaves the store and manifest consistent and only the derived graph needs a rebuild.
- **`sentence_transformers` is no longer imported at module load.** The CrossEncoder import is deferred into the model-load path, so the reranker module (and test collection) imports cleanly without the heavy ML stack installed.
- **OpenAI-SDK provider clients now use a bounded request timeout.** Every client was built without an explicit `timeout`, inheriting the SDK's 600s×2 default, which could wedge an index job uninterruptibly on a flaky link. Clients now default to 60s (cloud) / 120s (Ollama), overridable via `config.params`.

---

## [26.6.16] - 2026-06-04

### Changed
- **Setup wizard distinguishes CODE vs CHAT summarization and is plugin-aware.** The summarization provider always summarizes code during indexing and is only the chat fallback when the plugin is absent; the wizard explains this and reflects that chat summarization is OFF by default without the plugin (doubly opt-in). New wording-only `config wizard --chat-summarizer [plugin|provider|auto]` flag (default `auto`) — it doesn't change the written config; `setup.sh` decides the plugin before the wizard and passes it through.

### Fixed
- **Stuck-job recovery no longer loops forever on a poison job.** D14 auto-reindex re-enqueued every stale job on restart, including permanently-FAILED ones, minting fresh `retry_count=0` jobs and defeating the cap. Recovery now excludes permanently-FAILED jobs via `select_reenqueue_candidates`.
- **ChromaDB PostHog telemetry no longer spams `ERROR` logs.** chromadb 0.5.x calls `posthog.capture()` with positional args that posthog ≥ 3 rejects, and the documented off-switches aren't honored in 0.5.23; the server now neutralizes the telemetry client directly. No telemetry was ever sent.

## [26.6.15] - 2026-06-04

### Added
- **Multi-language BM25 tokenization.** Each document is tokenized with its own language analyzer (normalize → tokenize → stopwords → stem/lemmatize): ~27 Snowball languages plus a vendored Croatian stemmer, stopwords via `stopwordsiso`, unknown codes falling back to English. New `bm25:` config block (`language`, `engine`, `detect`, `detect_min_confidence`) with `init`/`folders add`/`query` flags and a `[lemma-hr]` extra for the high-accuracy Croatian lemmatizer.
- **`bm25s` scoring engine.** The BM25 backend is now `bm25s` directly, replacing the LlamaIndex wrapper; existing indexes auto-migrate by rebuilding from the stored corpus on first start (quality and API unchanged). The analyzer fingerprint is persisted, so changing `language`/`engine` triggers an auto-rebuild to stay in sync.

## [26.6.14] - 2026-06-04

### Changed
- **Session summarization default is now `subagent` (Claude-Code-only).** `session_extraction.mode` defaults to `subagent` in both CLI and server, so summarization happens only inside the plugin (free) and the server never falls back to a paid provider on its own — no surprise API bill. `provider`/`auto` remain an explicit opt-in; existing implicit-`auto` projects lose the server-side fallback until they set it by hand.
- **Provider distiller is now disabled by default (`SESSION_DISTILL_ENABLED`).** The kill switch flipped from default-on to default-off, so server-side (billable) summarization needs two locks lifted — `mode: provider`/`auto` and `SESSION_DISTILL_ENABLED=true`. (`SESSION_INDEXING_ENABLED`/`SESSION_ARCHIVE_ENABLED` are unchanged.)
- **Clarified "free" session summarization wording** — the plugin engine is "free on your Claude Code subscription" (draws on subscription limits), not unqualified "free", across docs and the wizard. Ollama remains the only truly-$0 option.

## [26.6.13] - 2026-06-03

### Added
- **Plugin-first engine with `auto` reconciliation.** `session_extraction.mode` defaults to `auto`: the server summarizes only when the plugin is absent and steps aside (24h safety net) when present, so installing/uninstalling flips the engine live. The plugin owns all 3 session hooks; a unified `.done` marker prevents re-summarizing on engine flips.
- **Throttled, cooldown-paced queue drain (`brainpalace drain-queue`).** The UserPromptSubmit drain releases a bounded batch (1 MB byte budget + 8 count cap; oversized sessions drain alone) and paces repeats with a 5-min cooldown. Knobs: `drain_budget_bytes` / `drain_max_count` / `drain_cooldown_seconds` (or `SESSION_DRAIN_*`).
- **`brainpalace status` shows session-summarization coverage** — percent of archived sessions with a durable extraction marker, engine-agnostic.
- **Automatic session summarization — on by default, guaranteed.** `init` enables distillation (`mode: auto`): subagent engine when the plugin is installed, else the provider engine. No code path silently skips a session (provider catch-up sweep + durable subagent queue); only `mode: off` or `SESSION_DISTILL_ENABLED=false` stop it.
- **`brainpalace backfill-sessions`** summarizes a project's pre-existing chats in the resolved engine (subagent → durable queue; provider → `POST /sessions/distill`, `--force` to re-distil).
- **CLI-only (provider) users are informed the plugin is cheaper** and that Ollama is recommended for transcripts (which can hold secrets). Informational only.

### Changed
- **Guided `setup.sh` banner shows the version to be installed** ("Version to install: X (latest on PyPI)") up front, including fresh installs.
- **Uninstall now flags a Claude Code marketplace plugin install.** Both `brainpalace uninstall` and `scripts/uninstall.sh` detect a marketplace install and print how to remove it via `/plugin` instead of deleting the cache (which would desync Claude Code's registry).

## [26.6.12] - 2026-06-02

### Changed
- **Plugin `/brainpalace-setup` is now global-first.** It writes provider config to the XDG global `config.yaml` (the same file the CLI uses) instead of the legacy `~/.brainpalace/`, adds an optional MCP-client wiring step, and makes project init the optional last step. Config-location docs were corrected to the XDG search order.
- **README install order:** "Install as a CLI or MCP server" now appears above the plugin section, with each command in its own code block.
- **Guided `setup.sh` UX polish:** detected API key shown as a green "✓ detected" tag, the MCP step lists auto-detected clients with an "other" escape hatch, declining the project step no longer duplicates next-steps, and the trailing "Docs:" list was removed.
- **`config wizard` prompts:** the summarization provider defaults to the embedding provider when it can summarize, else to whichever summarization key is set; the GraphRAG/Deployment prompts render the choice on its own line with neutral wording.
- **Guided setup prompts are spaced out** — a blank line precedes every question.

## [26.6.11] - 2026-06-02

### Changed
- **Guided `setup.sh`: the "install from a local checkout" prompt appears only when a checkout is detected,** so network (`curl | bash`) users no longer see a dev-only question; setup also warns the first pipx install pulls a large stack.
- **Guided `setup.sh`: when already installed, setup fetches the latest PyPI version** and shows it alongside the installed one ("update available" / "up to date") instead of a blind reinstall prompt.
- **Guided `setup.sh` is now global-first.** It installs, configures the provider globally (`config wizard --global`), and wires MCP at user scope first; setting up and indexing a project is the last, optional step (declining prints a copy-paste `init` example).

## [26.6.10] - 2026-06-02

### Added
- **`brainpalace init` is full setup by default.** A bare `init` writes config, starts the server, indexes the project (`watch=auto`), and archives + embeds transcripts; interactive runs show the plan and confirm once (declining falls back to config-only). New `--yes`/`-y`, `--no-start`, `--no-watch`; non-interactive / `--json` runs stay config-only unless `--yes`.

### Fixed
- **Uninstall no longer misreads a pipx/uv install as bare pip.** `detect_install_manager` classified the shim path verbatim; it now classifies the resolved symlink target and shebang, and the guided script retries with `--break-system-packages` for genuine system-pip installs.
- **`init` start/watch work without a `brainpalace` binary on PATH.** The nested `start` / `folders add` steps now fall back to `python -m brainpalace_cli` instead of raising `FileNotFoundError`.

### Changed
- **`init` output distinguishes status from actions** — it explains the cold-boot pause and background indexing, and splits completed actions under `Done:` from follow-ups under `Next steps:`.
- **Docs (INSTALL, README, USER_GUIDE) updated** for the new `init` default and the `--no-*` / `--yes` opt-outs.

## [26.6.9] - 2026-06-02

### Fixed
- **`init` no longer hardcodes the Anthropic summarizer.** The default config picks providers from the API keys present (summarization `anthropic → openai → gemini → grok`, embedding `openai → cohere`), so an OpenAI-only environment gets a working config with no edit; the global XDG config still wins.
- **`brainpalace start` / `stop` resolve the project root correctly in a mono-repo.** Both now import the canonical `config.resolve_project_root` (nearest `.brainpalace/` before git), instead of resolving a sub-project to the workspace root and reporting "Project not initialized".
- **`test_reset_index_success` is no longer order-dependent** — the reset tests override the symbols the route actually reads, and the conflict test forces the 409 path authoritatively.

## [26.6.8] - 2026-06-02

### Added
- **`brainpalace update`** — one-command upgrade that auto-detects pipx / uv / pip and runs the matching upgrade, then reminds you to restart the server (`--yes` skips the confirm).
- **`brainpalace uninstall` is now a guided teardown** with no flags: confirms each step (stop servers, remove plugin dirs, strip the `brainpalace` MCP entry while keeping others, delete selected state) and prints leftover manual steps. For pipx/uv it offers to run the package uninstall; `--yes`/`--json` keep the non-interactive behaviour.

## [26.6.7] - 2026-06-02

### Added
- **Guided uninstall — `scripts/uninstall.sh`.** Interactive teardown mirroring `setup.sh`: stops servers, removes plugin dirs, surgically strips the `brainpalace` MCP entry, uninstalls the package (auto-detected pipx/uv/pip), then offers per-project and global-state deletion. Shell rc is left to the user.
- **"Full uninstall (teardown)" docs** in `docs/INSTALL.md` and both skill installation guides, with a guided-uninstall curl one-liner.

### Fixed
- **Broken install URLs pointing at the local-only `stable` branch.** The README `setup.sh` one-liner and PLUGIN_GUIDE CI examples fetched `…/stable/…`, which 404s on GitHub; now `main`.
- **Documented a CLI command that does not exist.** `brainpalace uninstall --agent <runtime>` was referenced but never existed; replaced with direct `rm -rf` of the plugin dirs, and fixed `install-agent --scope global` → `--global`.

## [26.6.6] - 2026-06-02

### Changed
- **Session archiving is now independent of indexing and always-on by default.** Archive (free) and index (billable) are separate capabilities, each gated by its config/flag; existing projects with no `session_indexing` block now archive ON / index OFF. `init` writes both ON; `--no-sessions` / `--no-archive` disable each, with a new `SESSION_ARCHIVE_ENABLED=false` kill switch.
- **`retain_days <= 0` now means keep forever** (no age cutoff) for both index and the new `archive.retain_days`; defaults are `0`. ⚠️ First-run forever-indexing of a large transcript history can be a big embedding bill — set a positive `retain_days` to cap it.
- **Tool-tagged archive folders** are now `YYYY-MM-DD-<tool>` with a structured `tool` manifest field (the source of truth — don't parse paths). No migration; existing archives may be wiped (rebuildable from `~/.claude` within 30 days).
- **`brainpalace status`** now shows session archive and index on separate rows, covering all four on/off states.

### Fixed
- **Doc-freshness gate no longer false-positives on frontmatter-introduction.** `check_doc_freshness.py` treated the commit that adds a doc's `last_validated` block as a content change; frontmatter fences and blank lines are now recognised as metadata.

## [26.6.5] - 2026-06-02

### Fixed
- **Server no longer fails to start when the summarization provider's API key is absent.** `EmbeddingGenerator` built the summarization provider in its constructor, so a missing key crashed startup even though indexing only needs the embedding provider. The summarization provider is now built lazily on first summary (degrading to docstring extraction on error).

## [26.6.4] - 2026-06-01

### Fixed
- **File watcher / reindex now prunes deleted files.** Three coupled defects left a deleted file's chunk queryable and the document count stuck: the verifier failed eviction-only runs, the empty-docs early-return skipped the BM25 rebuild, and the manifest carried the deleted file over. Eviction-only runs now pass, rebuild BM25 from survivors, and keep only unchanged manifest entries.
- **`reset` and `folders remove` no longer leave stale manifests.** They kept `.brainpalace/manifests/*.json`, so the next `add`/`index` saw every file as unchanged and indexed 0 chunks into an empty store; `reset` now calls `delete_all()` and `remove_folder` deletes the folder's manifest.

### Changed
- **Session memory is ON by default for newly `init`-ed projects.** `init` writes `session_indexing.enabled: true` (interactive default yes); `--no-sessions` opts out. Applies only to a freshly written config — re-init and existing projects with no block stay off; only assistant/tool turns are indexed.

### Internal
- **Hardening:** a zero-change run whose store is empty but whose manifest claims indexed files now fails loudly instead of reporting done at 0%, surfacing a stale-manifest desync.

## [26.6.3] - 2026-06-01

### Changed
- **Session live-watcher debounce default raised 2s → 30s** (`session_indexing.watch_debounce_ms`). AI transcripts are written in per-message bursts, so the old window fired redundant re-index passes mid-turn; 30s batches a whole turn (the archive-deletion watcher stays at 1s).

### Internal
- **CI: GitHub Actions Node 20 → Node 24.** Bumped checkout/setup-python/cache/upload-artifact/codecov and set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` ahead of the 2026 default flip/removal.
- **Docs:** README usage examples, a Session Memory badge, and a note that automatic session capture is Claude-Code-transcript-specific (CLI or plugin).

## [26.6.2] - 2026-06-01

Durable, user-curatable session archive: session indexing now reads from a
local archive copy instead of the live `~/.claude` transcripts.

### Added
- **Session archive.** On a transcript change the raw `.jsonl` is copied verbatim into `.brainpalace/session_archive/<YYYY-MM-DD>/` and indexing runs off the copy (`~/.claude` is read-only), so sessions survive Claude Code removal/auto-delete. Opt-out via `session_indexing.archive.enabled`.
- **Curation by deletion.** Deleting an archived transcript (or a dated folder) purges that session's chunks and writes a tombstone, so the live source is never re-synced.
- **Provenance.** Chunks record `origin_path` (live source) alongside `source_path` (archive copy).
- **Status.** `brainpalace status` / `/status` report `archived_sessions`, `archived_files`, `archived_bytes`, and `tombstoned`.
- **`brainpalace reset --include-sessions`** also deletes the archive; a plain reset preserves it.

### Fixed
- **Chunk purge never worked** — a flat multi-key ChromaDB `where` filter that ChromaDB rejects; now wrapped in `$and`.
- **Subagent transcripts collided with their parent** under a `session_id`-keyed manifest (undercount + a data-loss path where deleting one subagent purged the parent). The manifest is now keyed per file; a session is purged only when all its files are gone.

## [26.6.1] - 2026-06-01

Second release: watcher/session-memory/status fixes plus first-run UX and
correctness fixes found during integration testing.

### Added
- **`index --watch` / `--watch-debounce`** — mark a folder live-watched (or `--watch off`); the `FileWatcherService` re-indexes on change with a tunable debounce.
- **`init --sessions` session memory** — opt-in, privacy-first indexing of this project's AI chat transcripts (assistant + tool turns), default off.
- **`status` per-feature view** — document indexing, file watcher (with a "0 folders" state), session memory, and graph index.
- **`init --start` provider pre-flight** — validates embedding + summarization providers before launching, failing fast with the missing env var.

### Fixed
- **Session chunks upsert to Chroma** — the chunker stored list/`None` metadata that Chroma rejects, crashing session indexing at boot; lists are now comma-joined and unset keys dropped.
- **`folders add` watch default** — bare `folders add .` now defaults to `--watch auto` (was `off`), matching the docs.
- **Summarization `api_key_env` ignored the provider** — the conventional env var is now derived from the selected provider when unset, and error messages name the correct one.
- **`init --start` re-run** — re-running after a pre-flight abort now starts the server idempotently instead of hitting the already-initialized no-op.
- **`init --force`** — no longer overwrites a user-edited `config.yaml` (provider/storage/graphrag settings are preserved).
- **`status` `total_documents`** — derived from persisted manifests, so it's correct even when indexing ran in the job worker.

### Docs
- **Documented the session-memory embedding cost** (50% sliding-window overlap at `window=4`/`stride=2`; `stride: 4` ~halves it) in SESSION_INDEXING.md and CLAUDE.md.

## [26.5.1] - 2026-05-30

First public release of BrainPalace.

### Highlights
- **Hybrid retrieval** — BM25 + vector + GraphRAG, fused (`hybrid`/`multi`) or selectable per call (`bm25`/`vector`/`graph`).
- **Session intelligence** — curated memory (`remember`/`recall`) + session-start context injection; session indexing into searchable summaries, decisions, and a typed knowledge graph with cross-session supersession.
- **Persistent SQLite graph backend** with temporal validity (per-edge validity windows, `invalidate`, `timeline`).
- **Time-decay ranking**, **git-history indexing**, and an opt-in **LSP cross-reference** symbol graph.
- **AST-aware code chunking** (Python, TS/JS, Java, Kotlin, C/C++, C#, Go, Rust, Swift), optional **LLM code summaries**, opt-in **cross-encoder reranking**.
- **Multi-instance** (one server per project, auto port allocation + `runtime.json` discovery), **file watcher**, **incremental indexing**, **embedding cache**.
- **Interfaces** — CLI (`brainpalace` / `bp`), opt-in **MCP server**, and a **Claude Code plugin** (30 slash commands, 3 agents, 2 skills).
- **Pluggable providers** — embeddings (OpenAI · Cohere · Ollama), summarisation (Anthropic · OpenAI · Gemini · Grok · Ollama); fully-local via Ollama.

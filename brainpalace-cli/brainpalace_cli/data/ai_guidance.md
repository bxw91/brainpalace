<!--
SINGLE SOURCE OF TRUTH for AI-facing BrainPalace usage guidance.
Edit HERE only. Do NOT hand-edit generated copies:
  - brainpalace-plugin/skills/using-brainpalace/SKILL.md   (generated FULL tier)
  - MCP Server(instructions=...)                            (reads CORE tier)
  - SessionStart hook additionalContext                     (reads CORE tier, via `brainpalace hook`)
See CLAUDE.md → "AI-guidance parity". Verified against code on the date below.

meta: version=7.9.0 last_validated=2026-07-17

Tiers:
  CORE = the marked slice below (between the CORE open/close HTML markers). The
         decision contract; cheap enough to inject on every session start / MCP
         connect. Keep under budget.
  FULL = the entire body (CORE + the sections after it). Pulled on demand:
         `brainpalace ai-guide --tier full`, or the `ai_guide` MCP tool.
NOTE: this header is the only HTML comment with no nested markers, so the loader
strips it cleanly. Do not write the literal marker tokens inside this comment.
-->

# BrainPalace Expert Skill

Search indexed docs / code with five modes: BM25 (keyword), Vector (semantic),
Hybrid (fusion), Graph (knowledge graph), Multi (comprehensive fusion).

This is the **search decision contract**. Operational reference (indexing,
injection, jobs, cache, server lifecycle, per-mode deep dives) lives in the
**Reference Documentation** table at the end — look it up on demand; the CLI's
own `--help` is authoritative for flags.

<!--CORE-->
<!--NUDGE-->
**BrainPalace is indexed for this project — search via `brainpalace query`, not
Glob/Grep.** Route by query type: exact symbol/token/path → `--mode bm25`
(keyword index, **no embedding round-trip** — ms latency, as fast as grep);
concept → `--mode vector`/`hybrid`; relationships → `--mode graph`. Server down?
Start it: `brainpalace start`; if it answers `503` "rehome pending" the project
MOVED — run `brainpalace rehome --resume` (or restart; it auto-resumes) first.
`brainpalace query --json` keys are
`text`/`source`/`score`/`chunk_id`/`start_line`/`end_line` (no `file_path`;
lines null off-code); on failure stdout is `{"error": ...}` with no `results`
key and a non-zero exit — check it, never append `2>/dev/null`.
<!--/NUDGE-->

## Mode Decision Table — Quick Reference

Pick `--mode` for any inline search. Default to `hybrid` when unsure.

| Query type | Mode |
|---|---|
| General / unknown | `--mode hybrid` |
| Conceptual ("how does X work") | `--mode vector` |
| Exact symbol / error / token / file path | `--mode bm25` |
| Relationships ("what calls X", "what imports Y") | `--mode graph` |
| Maximum recall (ALL usages / references) | `--mode multi` |
| Aggregation ("how many", "total", "which week had most") | `--mode compute` |
| Own-utterance history ("which week did I mention X") | `--mode scan` |
| Anti-join over typed records ("X but not Y") | `--mode absence` |
| Belief/fact evolution ("how did X evolve", "history of X") | `--mode timeline` |

Common flags: `--top-k N` (default 5), `--threshold F` (default 0.3),
`--alpha F` (hybrid balance, 0=BM25…1=Vector, default 0.5), `--language CODE`
(per-query BM25 tokenization override; bm25/hybrid only).

Docs rank below code (`ranking.doc_weight`=0.5 default); `--source-types code`
filters.

### Before Anything Else — Project Indexed Check

Run this **first**:

```bash
brainpalace whoami    # exits 0 (indexed + server up), 1 (no project), or 2 (indexed but server down)
```

- **Exit `0`** → `.brainpalace/` exists AND server running. Skill applies.
- **Exit `1`** → no `.brainpalace/` in CWD or any ancestor. **Skill yields silently** —
  use native Glob/Grep/Read as normal. Optionally suggest `brainpalace init`. Do
  NOT print enforcement warnings; do NOT block the task.
- **Exit `2`** → indexed but server not running. Searches fail until started —
  follow "When the server is down" below.

CLI not installed (command not found) → treat as exit `1`, yield.

### Search Rule — Non-Negotiable (when indexed)

When the check passed, BrainPalace is the first entry point for codebase search.
Never use Glob, Grep, or Bash `find`/`grep`/`rg` against indexed project source — even
when you think you know the path or token (see the NUDGE rationale above). Pick
a mode, then:

```bash
brainpalace query "..." --mode <picked> --top-k 8 --json
```

After BrainPalace returns confirmed file paths, use `Read` to open them.

### Parsing `--json` Output

Per-result keys are `text`, `source`, `score`, `chunk_id`, `start_line`,
`end_line` (`int | null`, null off-code) — there is NO `file_path` or
`content` field. On failure, stdout is
`{"error": ...}` (with `detail`/`hint`) and a non-zero exit, with **no**
`results` key. Never append `2>/dev/null` — diagnostics go to stderr. A
top-level `index_blocked` object means the index is STALE (paused over
budget) — never auto-approve. (Runnable parsing snippet: `--tier full`.)

**Allowed Glob/Grep (NOT codebase search):** inside a file BrainPalace already
returned; non-indexed paths (`~/.claude/`, `~/.config/`, `/tmp/`, dotfiles,
settings/logs); files changed since `last_indexed`; paths in `exclude_patterns`;
listing directory STRUCTURE only (`ls`, `find <path> -maxdepth N -type d`).

### When the Server Is Down

If `brainpalace query` returns connection-refused / `/health/` non-200 (indexed
but server not running):
1. Task needs codebase search → STOP. Tell the user: "BrainPalace server not
   running. Start it with `brainpalace start`."
2. Task does NOT need codebase search → proceed normally.
3. NEVER fall back to Glob/Grep/find for codebase search "just this once".

Server-down (`.brainpalace/` exists, process not running) is distinct from
not-indexed (no `.brainpalace/` at all → the skill yields).

**Sensitivity:** `sensitivity != "normal"` rows (records, graph nodes, session
chunks, memory — incl. private-session derivatives) are hidden by default
everywhere, incl. memory recall/boost/session-context. `--include-sensitive`
reveals, CLI-only; MCP/dashboard never reveal.

Full detail: `brainpalace ai-guide --tier full` (MCP: the `ai_guide` tool).
<!--/CORE-->

---

## Parsing `--json` Output — runnable example

```bash
brainpalace query "..." --mode hybrid --top-k 8 --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'error' in d: sys.exit('brainpalace error: %s' % d['error'])
for r in d['results']:
    print(r['source'], r['score'])
    print(r['text'][:500])
"
```

---

## Content Filters — `--domain` / `--meta`

`--domain D` (repeatable, OR) scopes results to chunks ingested under that
`/ingest` domain (the reserved `domain` metadata key — an owner or app
namespace). `--meta k=v` (repeatable, AND across keys) exact-matches any
chunk metadata key, including `/ingest`'s reserved `source`/`source_id`.
Both compose with `--source-types`/`--languages`/`--file-paths` and with
sensitivity default-deny.

---

## Paused (Budget-Blocked) Indexing

Query output (CLI `--json` and the MCP `query` tool) may carry a top-level
`index_blocked` object: `{job_id, folder_path, estimated_tokens, limit,
blocked_since}`. It means an indexing job was PAUSED by the embedding-token
budget: the server is up but the index for that folder is STALE. Nothing was
spent.

1. Tell the user: indexing is paused, results may be stale, and approving
   will spend ~`estimated_tokens` embedding tokens.
2. NEVER approve on your own — approving spends money. Ask the user first.
3. On explicit consent: `brainpalace jobs <job_id> --approve` (over MCP: the
   `jobs_approve` tool). To raise the cap instead, increase
   `indexing.max_embed_tokens_per_job` via `brainpalace config wizard` (or set
   the `INDEX_MAX_EMBED_TOKENS` env var), then approve.

---

## Subagent Dispatch — codebase search

When you delegate codebase search/exploration to a subagent, dispatch the
`research-assistant` agent (`subagent_type: research-assistant`): it has `Glob`
and `Grep` disabled and searches via BrainPalace only, so it cannot quietly fall
back to filesystem grep. Avoid generic search subagents (e.g. `Explore`) for code
lookup — they retain grep/find and will bypass the index. The PreToolUse subagent
guard (`cli.subagent_guard`, on by default while the server runs) reinforces this:
it acts only on *search-shaped* `Agent`/`Task` spawns (a prompt that asks to find,
locate, trace, list callers, etc.) whose prompt lacks a `brainpalace query --mode`
directive (or the equivalent MCP query-tool `mode:` argument). By default it
`enforce`-denies such a spawn with a fix hint; non-search spawns pass untouched and
`research-assistant` is allowlisted. Soften to a nudge with
`cli.subagent_guard.mode: advisory` (or `BRAINPALACE_SUBAGENT_GUARD=advisory`). For
a genuine exemption, open the prompt with `# BRAINPALACE_EXEMPT: <reason of 20+ chars>`.

---

## Compute Mode — Aggregation over Typed Records

`--mode compute` answers set-level questions (sum/count/avg/superlative) over
**typed numeric records** persisted from session distillation — not document
chunks. It is **auto-routed**: queries containing "how many", "total", "which
week had most", etc. are classified as compute-intent and routed to this mode
automatically, falling back to `hybrid` when no metric resolves or records are
empty.

**What records exist:** HIGH-confidence records are populated from session
distillation. Phase 1 derives counts automatically (files touched, tools used,
decisions, open threads — unit `count`, confidence 1.0). LLM-extracted numeric
measurements (weight, sales, etc.) are stored as PROVISIONAL until a teaching
loop validates them (Phase 4). For now, rely on `compute` for count-type
queries; treat other metrics as experimental until taught.

**Supported operations:** `sum`, `count`, `avg` (explicit), plus superlatives
(`which X had the most/least Y` → `sum` per group, ordered desc/asc, limit 1).
Grouping by `week` (ISO), `month` (`YYYY-MM`), `source`, `subject`, or `unit`.

**`--json` contract for compute:** `results` is always `[]`; rows live under
`compute`. Each row: `label` (group key or `null`), `value` (float),
`metric`, `op`, `group` (group_by or `null`), `unit`, `score`.

```bash
brainpalace query "how many files did I touch per week" --mode compute --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'error' in d: sys.exit('brainpalace error: %s' % d['error'])
for row in d.get('compute', []):
    print(row['label'], row['value'], row['unit'])
"
```

Compute query mode has no switches — it is always selectable and returns empty
when no records exist. Records are extracted automatically whenever session
extraction runs (gated by `extraction.mode`); there is no separate
record toggle. The only compute knob is `compute.min_confidence` in
`.brainpalace/config.yaml`.

---

## Scan Mode — Term Counts over Session Transcripts

`--mode scan` counts a term/phrase over the archived session transcripts,
bucketed by week/month/day/source — "which week did I say X most".
Deterministic and free (no LLM, no embedding). Empty when the session archive
is off or no term parses. Tie-break with compute: typed record metric wins.

**`--json` contract for scan:** `results` is always `[]`; rows live under
`scan`. Each row: `label`, `value` (float count), `term`, `group`
(bucket or `null`), `score`.

---

## Absence Mode — Anti-Join over Typed Records

`--mode absence` — anti-join over typed records: subjects present under one
partition value (`metric`/`source`/`domain`) but absent under another
("distance but not duration"). Deterministic, no LLM. Empty when no two
stored values resolve, or nothing qualifies (e.g. no records exist).
Auto-routed after compute and scan — a query carrying a compute or scan tell
alongside an absence tell routes there instead (e.g. "did I discuss gmail but
not session" is scan, not absence, because it carries "did i discuss").

**`--json` contract for absence:** `results` is always `[]`; rows live under
`absence`. Each row: `label` (the missing subject), `present_in`,
`absent_from`, `partition` (`metric`/`source`/`domain`), `score` (reserved,
always `0.0`).

---

## Timeline Mode — Edge-Validity / Supersession History

`timeline` — walk an entity's edge-validity/supersession history in the graph:
how a belief/fact evolved ("how did the auth decision evolve", "history of
auth.py"). Deterministic, no LLM. Requires the graph index (`ENABLE_GRAPH_INDEX`);
empty when the named entity resolves to no graph node or has no edges.
Auto-routed after compute, scan, and absence — a query carrying one of those
tells alongside a timeline tell routes there instead.

**`--json` contract for timeline:** `results` is always `[]`; rows live under
`timeline`. Each row: `subject`, `predicate`, `object`, `valid_from`,
`valid_until` (`null` = still valid), `valid`, `score`.

---

## Session Memory — Optional, Separately Gated

Recall of prior AI-coding sessions (past-session transcript chunks and distilled
decisions) is an **optional feature, gated independently** of document search.
When it is enabled, the SessionStart context block tells you so and how to reach
it; when it is off, that data is hidden from results and no recall instruction
appears. So never assume session recall is always available — act on the context
block you actually receive, not on a fixed expectation. Manually-saved memory
(`brainpalace remember`) is always available via `brainpalace recall`.

---

## Reference Catalog — Lazy-Tier Pointers

AI clients may search references: `brainpalace references search "<query>"`
semantically searches summary text over the lazy-tier reference catalog
(pointer + summary entries for sources fetched-and-extracted on demand — not
yet embedded as full document chunks). Top matches also surface inline in
`hybrid`/`vector`/`multi`/`graph` results, tagged `type: reference`, so you
may see one without searching for it directly. `brainpalace references
resolve <id>` prints the stored pointer + summary; ingest the resolved body
as searchable text via `brainpalace ingest` when you need it in full.

---

## When Not to Use

This skill focuses on **searching and querying**. Do NOT use for installation,
API-key configuration, server setup, or provider configuration — use the
`configuring-brainpalace` skill. Assumes BrainPalace is already installed,
configured, and running with indexed documents.

---

## Reference Documentation

Per-mode deep dives, tuning, and examples (links resolve in the plugin skill):

| Guide | Description |
|-------|-------------|
| [BM25 Search](references/bm25-search-guide.md) | Keyword matching, `--language` override, threshold tuning |
| [Vector Search](references/vector-search-guide.md) | Semantic similarity for concepts |
| [Hybrid Search](references/hybrid-search-guide.md) | Combined keyword + semantic, `--alpha` tuning |
| [Graph Search](references/graph-search-guide.md) | GraphRAG, relationship/dependency queries, traversal depth |
| [Server Discovery](references/server-discovery.md) | Auto-discovery, multi-instance sharing, lifecycle |
| [Provider Configuration](references/provider-configuration.md) | Environment variables and API keys |
| [Integration Guide](references/integration-guide.md) | Scripts, Python API, CI/CD, cache management |
| [API Reference](references/api_reference.md) | REST endpoints, indexing/folders/jobs, eviction summary |
| [Troubleshooting](references/troubleshooting-guide.md) | Common issues and solutions |

Operational commands not covered above are self-documenting via `--help`:
`brainpalace index|folders|jobs|cache|inject|types <…> --help`. Content-injection
authoring (the `process_chunk` protocol) is specified in `docs/INJECTOR_PROTOCOL.md`.

---

## Graph verbs (path / impact / co-change)

Beyond `--mode graph` retrieval, three CLI verbs answer structural questions
directly (SQLite graph store only — no embedding call, works on any backend):

```bash
brainpalace graph path <src> <dst> --json    # shortest edge paths between two nodes
brainpalace graph impact <node> --json       # what transitively depends on the node
brainpalace graph cochange <file> --json     # files that change together (git history)
```

Reference nodes by canonical id (absolute file path, or `path:fqname` for a
symbol) or by a unique display name; an ambiguous name fails with the
candidate ids listed. On failure stdout is `{"error": ...}` with a non-zero
exit — same contract as `query --json`. `cochange` needs `git_indexing`
enabled.

---

## Cross-instance search (household multi-instance)

Cross-instance search: `query --also <path-or-url>` (repeatable) fans a query
out to sibling BrainPalace instances and RRF-merges the results, tagging each
`--json` result with an `"instance"` key (`"local"` or the sibling's
path/URL); a down sibling warns on stderr and is skipped (local results still
render).

---

## Limitations

- Vector/hybrid/graph/multi modes require an embedding provider configured
- Graph mode requires additional memory (~500MB extra); GraphRAG is enabled by default (`graphrag.enabled: true` / `ENABLE_GRAPH_INDEX`), disable with `ENABLE_GRAPH_INDEX=false`
- Supported formats: Markdown, PDF, plain text, code files (Python, JS, TS, Java, Go, Rust, C, C++)
- Not supported: Word docs (.docx), images
- Server requires ~500MB RAM for typical collections (~1GB with graph)
- Ollama requires local installation and model download

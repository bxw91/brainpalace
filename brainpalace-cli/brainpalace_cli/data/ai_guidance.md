<!--
SINGLE SOURCE OF TRUTH for AI-facing BrainPalace usage guidance.
Edit HERE only. Do NOT hand-edit generated copies:
  - brainpalace-plugin/skills/using-brainpalace/SKILL.md   (generated FULL tier)
  - MCP Server(instructions=...)                            (reads CORE tier)
  - SessionStart hook additionalContext                     (reads CORE tier, via `brainpalace hook`)
See CLAUDE.md → "AI-guidance parity". Verified against code on the date below.

meta: version=7.4.0 last_validated=2026-06-16

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
Start it: `brainpalace start`. `brainpalace query --json` keys are
`text`/`source`/`score`/`chunk_id` (no `file_path`, no line numbers); on failure
stdout is `{"error": ...}` with no `results` key and a non-zero exit — check it,
never append `2>/dev/null`.
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

Common flags: `--top-k N` (default 5), `--threshold F` (default 0.3),
`--alpha F` (hybrid balance, 0=BM25…1=Vector, default 0.5), `--language CODE`
(per-query BM25 tokenization override; bm25/hybrid only).

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

If the `brainpalace` CLI is not installed (command not found), treat as exit `1` and yield.

### Search Rule — Non-Negotiable (when indexed)

When the check passed, BrainPalace is the first entry point for codebase search.
Never use Glob, Grep, or Bash `find`/`rg` against indexed project source — even
when you think you know the path or token. This is not a latency trade: an exact
symbol/token/path lookup goes to `--mode bm25`, which queries the local keyword
index with **no embedding round-trip**, returning in milliseconds (vector/hybrid
pay the embed call, so reserve them for conceptual queries). Pick a mode, then:

```bash
brainpalace query "..." --mode <picked> --top-k 8 --json
```

After BrainPalace returns confirmed file paths, use `Read` to open them.

### Parsing `--json` Output

Per-result keys are `text`, `source`, `score`, `chunk_id` — there is NO
`file_path`, `content`, or line-number field. On failure, stdout is
`{"error": ...}` (with `detail`/`hint`) and a non-zero exit, with **no**
`results` key. Never append `2>/dev/null` — diagnostics go to stderr.

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

**Allowed Glob/Grep cases (NOT codebase search):** searching inside a single file
BrainPalace already returned; non-indexed paths (`~/.claude/`, `~/.config/`,
`/tmp/`, dotfiles, settings/logs); files modified since `last_indexed`
(`brainpalace folders list`); paths in the project's `exclude_patterns`; listing
directory STRUCTURE only (`ls`, `find <path> -maxdepth N -type d`).

### When the Server Is Down

If `brainpalace query` returns connection-refused / `/health/` non-200 (indexed
but server not running):
1. Task needs codebase search → STOP. Tell the user: "BrainPalace server not
   running. Start it with `brainpalace start`."
2. Task does NOT need codebase search → proceed normally.
3. NEVER fall back to Glob/Grep/find for codebase search "just this once".

Server-down (`.brainpalace/` exists, process not running) is distinct from
not-indexed (no `.brainpalace/` at all → the skill yields).

For full operational detail run `brainpalace ai-guide --tier full` (or, over MCP,
call the `ai_guide` tool).
<!--/CORE-->

---

## Subagent Dispatch — codebase search

When you delegate codebase search/exploration to a subagent, dispatch the
`research-assistant` agent (`subagent_type: research-assistant`): it has `Glob`
and `Grep` disabled and searches via BrainPalace only, so it cannot quietly fall
back to filesystem grep. Avoid generic search subagents (e.g. `Explore`) for code
lookup — they retain grep/find and will bypass the index. The PreToolUse subagent
guard (`cli.subagent_guard`, on by default while the server runs) reinforces this:
it nudges `Agent`/`Task` spawns whose prompt lacks a `brainpalace query --mode`
directive (or the equivalent MCP query-tool `mode:` argument), and in opt-in
`enforce` mode denies them; `research-assistant` is allowlisted. For a genuine
exemption, open the prompt with `# BRAINPALACE_EXEMPT: <reason of 20+ chars>`.

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

## Session Memory — Optional, Separately Gated

Recall of prior AI-coding sessions (past-session transcript chunks and distilled
decisions) is an **optional feature, gated independently** of document search.
When it is enabled, the SessionStart context block tells you so and how to reach
it; when it is off, that data is hidden from results and no recall instruction
appears. So never assume session recall is always available — act on the context
block you actually receive, not on a fixed expectation. Manually-saved memory
(`brainpalace remember`) is always available via `brainpalace recall`.

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

## Limitations

- Vector/hybrid/graph/multi modes require an embedding provider configured
- Graph mode requires additional memory (~500MB extra); GraphRAG is enabled by default (`graphrag.enabled: true` / `ENABLE_GRAPH_INDEX`), disable with `ENABLE_GRAPH_INDEX=false`
- Supported formats: Markdown, PDF, plain text, code files (Python, JS, TS, Java, Go, Rust, C, C++)
- Not supported: Word docs (.docx), images
- Server requires ~500MB RAM for typical collections (~1GB with graph)
- Ollama requires local installation and model download

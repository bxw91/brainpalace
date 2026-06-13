<!--
SINGLE SOURCE OF TRUTH for AI-facing BrainPalace usage guidance.
Edit HERE only. Do NOT hand-edit generated copies:
  - brainpalace-plugin/skills/using-brainpalace/SKILL.md   (generated FULL tier)
  - MCP Server(instructions=...)                            (reads CORE tier)
  - SessionStart hook additionalContext                     (reads CORE tier, via `brainpalace hook`)
See CLAUDE.md → "AI-guidance parity". Verified against code on the date below.

meta: version=7.3.0 last_validated=2026-06-13

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
**BrainPalace is indexed for this project — prefer `brainpalace query` over
Glob/Grep for codebase search.** If the server is not running, start it with
`brainpalace start`. `brainpalace query --json` result keys are
`text`/`source`/`score`/`chunk_id` (no `file_path`, no line numbers); on failure
stdout is `{"error": ...}` with no `results` key and a non-zero exit — check for
it, and never append `2>/dev/null` to brainpalace commands.
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
when you think you know the path or token. Pick a mode, then:

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

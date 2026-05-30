---
last_validated: 2026-05-29
---

# Session-Start Context

A compact, budget-capped **frozen snapshot** the AI loads once at the start of a
session so it begins already knowing the project's durable facts — the proactive
*push* that complements the curated-memory *boost* (see [MEMORY.md](MEMORY.md)).

```bash
brainpalace context          # print the block (for a SessionStart hook)
brainpalace context --json   # structured form
```

## What's in the block

In priority order, capped to `CONTEXT_BUDGET_TOKENS` (default 3000, ≈ chars/4):

1. **Project facts** — repo root, current branch, indexed chunk count. Always
   present; tiny.
2. **Curated memory** — active entries from the memory namespace (Phase 030),
   highest-confidence / most-recent first, added until the budget is reached.
3. **Last-session summary** — *placeholder.* Filled once Phase 050
   (session-ingest) lands; absent from `sections` until then.

The response reports `sections` (what's actually included), `token_estimate`,
`truncated` (some memories dropped for budget), and `memory_count`.

> **Frozen snapshot.** Loaded once per session. Mid-session memory writes persist
> to disk but only appear in the *next* session's block — this keeps the prompt
> prefix stable (prefix-cache friendly) and the context predictable.

## Wiring it (Claude Code SessionStart hook)

The plugin ships `templates/sessionstart-hook.sh`. When the project is indexed
and the server is up, it appends `brainpalace context` output to the session's
`additionalContext`. Install:

```bash
cp brainpalace-plugin/templates/sessionstart-hook.sh \
   ~/.claude/hooks/brainpalace-sessionstart.sh
chmod +x ~/.claude/hooks/brainpalace-sessionstart.sh
# reference it under hooks.SessionStart in ~/.claude/settings.json (see the
# template header for the exact JSON)
```

The hook **fails soft** — if the server is down or context errors, it never
blocks session start. Other runtimes (Gemini CLI, Codex, MCP clients) call
`brainpalace context` or the `session_context` MCP tool directly.

## Endpoint & MCP

- `GET /context/session-start` → `SessionContext` (`503` when
  `CONTEXT_ENABLED=false`).
- MCP tool `session_context`.

## Tiered retrieval ladder

The frozen snapshot is **Tier 0** of the recall contract the AI follows. Escalate
only when the prior tier misses — cost climbs each step:

| Tier | Source | Cost | When |
|---|---|---|---|
| **Tier 0** | injected snapshot (this block — facts + curated memory) | free (in context) | always; already loaded |
| **L1** | `query` — vector + BM25 + RRF over the index | embed/query | semantic recall, different wording |
| **L2** | expand — surrounding chunks / full section around an L1 hit | cheap | need more context around a match |
| **L3** | raw transcript (verbatim, by session) | disk read | exact dialogue *(Phase 050)* |
| **Graph** | multi-hop / timeline over the knowledge graph | query | "what superseded X", supersedes chains *(Phase 090/100)* |

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `CONTEXT_ENABLED` | `true` | master switch for the session-start block |
| `CONTEXT_BUDGET_TOKENS` | `3000` | block budget (≈ chars/4 estimate) |

The budget is a directional estimate; the block is small and the memory slice is
already bounded by `MEMORY_CHAR_CAP` (Phase 030).

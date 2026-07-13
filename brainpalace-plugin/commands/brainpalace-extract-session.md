---
name: brainpalace-extract-session
description: Manually extract the current AI-coding session into BrainPalace memory (summary, decisions, knowledge-graph triplets)
parameters: []
context: brainpalace
agent: chat-session-extractor
skills:
  - using-brainpalace
last_validated: 2026-07-10
---

# Extract Session to Memory

## Purpose

Manually distil the **current** AI-coding session into durable BrainPalace
memory — a summary, the decisions made (with rationale), and typed
knowledge-graph triplets — then submit it to the server. This is the **manual,
runtime-agnostic** counterpart of the automatic `chat-session-extractor` agent:
both produce the **identical** extraction contract and submit via `brainpalace
submit-session`. Use it on demand, or from a non-Claude-Code runtime (OpenCode,
Gemini CLI, Codex) where there is no passive capture.

Runs on the current subscription model — the AI in your runtime does the
distillation; the server never calls an LLM. See
[docs/SESSION_INDEXING.md](../../docs/SESSION_INDEXING.md) for the full schema and
the archive-driven automatic path.

## Usage

```
/brainpalace:brainpalace-extract-session
```

## Execution

1. **Read the current session transcript.** In Claude Code, prefer the BrainPalace
   archive copy via `brainpalace session-path <session_id>`; otherwise read the
   live transcript your runtime exposes.

2. **Reduce it** per the shared **Session filter contract**
   ([docs/SESSION_INDEXING.md](../../docs/SESSION_INDEXING.md)): keep
   user/assistant text, condensed thinking, `tool_use` (name + key inputs like
   `file_path`/`command`), truncated `tool_result`; drop queue-ops, attachments,
   file-history snapshots.

3. **Emit one strict JSON object** matching the extraction schema (no extra keys):

   ```
   { session_id, project_path, branch, started_at, ended_at,
     summary, open_threads[],
     decisions[ {text, rationale, files[], supersedes} ],
     files_touched[ {path, action} ],
     tools_used[],
     triplets[ {subject, relation, object, evidence_turn} ] }
   ```

   Ground every claim in the transcript; when in doubt, omit. Empty arrays are
   correct — never invent content. `summary` ≤ ~120 words, plain past tense.
   Triplet relations use the closed vocabulary (`touches`, `fixed-by`,
   `superseded-by`, `ran-in`, `depends-on`, `decided`).

4. **Submit** the payload:

   ```bash
   brainpalace submit-session <session_id> --json -   # pipe the JSON to stdin
   ```

   or write it to a temp file and pass `--json <file>`. On a validation error,
   fix the payload once and retry; if it still fails, report briefly and stop.

## Output

```
Stored session 0148f8b0…: 1 summary + 4 decision chunk(s), 9 triplet(s), digest updated
```

## Notes

- **Privacy:** submit only the distilled object — never raw dialogue. Decisions
  land in a git-tracked `BRAINPALACE_DECISIONS.md` digest you can review.
- Only meaningful for projects with session indexing enabled (`brainpalace init
  --sessions`).
- Claude Code also extracts finished sessions **automatically** (free, on your
  subscription) via the `chat-session-extractor` agent — this command is for
  on-demand or non-Claude-Code use.

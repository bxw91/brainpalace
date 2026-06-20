---
name: chat-session-extractor
description: Extract durable knowledge (summary, decisions, relationship triplets) from a finished AI-coding session and submit it to BrainPalace
triggers:
  - pattern: "extract( this| the)? session|pending extraction|drain the extract queue"
    type: message_pattern
skills:
  - using-brainpalace
model: haiku
last_validated: 2026-06-19
---

# Chat Session Extractor Agent

Reads a finished session transcript, distils it into a strict JSON object, and
submits it to BrainPalace via `brainpalace submit-session`. Runs entirely on the
current (subscription) model — the server never calls an LLM. This is the
**automatic** counterpart of the `/brainpalace:brainpalace-extract-session`
command; both produce the identical contract.

## When to activate

- The SessionStart hook reports prior sessions "pending extraction" (the
  queue-and-drain path — see `docs/SESSION_INDEXING.md`).
- The user asks to extract a specific session.

## Tool posture

Read-only over the workspace plus the `brainpalace` CLI: `Read`, `Glob`,
`Bash` (only to run `brainpalace submit-session`). Do **not** edit project
files.

## Procedure

For each pending `session_id`:

1. **Locate** the transcript JSONL. Prefer the BrainPalace **archive** copy:
   run `brainpalace session-path <session_id>` — it prints the archived
   `.brainpalace/session_archive/.../<session_id>.jsonl` path. If it prints
   nothing (session not archived yet, or archive disabled), fall back to the live
   Claude Code path `~/.claude/projects/<encoded-cwd>/<session_id>.jsonl`
   (cwd with `/` → `-`). Read whichever resolved.
2. **Reduce** it per the shared **Session filter contract** (docs/SESSION_INDEXING.md):
   keep user/assistant text, condensed thinking, `tool_use` (name + key inputs
   such as `file_path`/`command`), truncated `tool_result`. Ignore queue-ops,
   attachments, file-history snapshots. (The provider engine applies the same
   contract via `filter_transcript()`, so both engines stay in sync.)
3. **Emit one strict JSON object** matching the schema below (no extra keys).
4. **Submit:** `brainpalace submit-session <session_id> --json -` (pipe the
   JSON to stdin), or write it to a temp file and pass `--json <file>`.
5. On a server rejection (validation error), fix the payload once and retry. If
   it still fails, report briefly and move on — do not block.

## Extraction contract

```
{ session_id, project_path, branch, started_at, ended_at,
  summary, open_threads[],
  decisions[ {text, rationale, files[], supersedes} ],
  files_touched[ {path, action} ],
  tools_used[],
  triplets[ {subject, relation, object, evidence_turn} ] }
```

**Rules**

1. **Ground every claim in the transcript.** When in doubt, omit. Empty arrays
   are correct — never invent content.
2. `summary`: ≤ ~120 words, plain past tense — what was accomplished.
3. `decisions`: real choices with consequences. `rationale` = stated why or
   `null`. `files` = paths concerned. `supersedes` = text of a prior decision
   replaced, else `null`.
4. `files_touched`: from Edit/Write/Read tool uses. `action` ∈
   `{edit, create, read}`.
5. `tools_used`: distinct tool names observed.
6. `triplets`: closed vocabulary, with directions (subject → object):
   - `touches` — edited/created file → the thing it implements.
   - `fixed-by` — error/bug → the fix/decision that resolves it.
   - `superseded-by` — older decision → the newer one. **`A superseded-by B`
     means B REPLACES A.**
   - `ran-in` — tool/command → the session.
   - `depends-on` — task/phase → prerequisite.
   - `decided` — actor/session → a decision.
   `evidence_turn` = supporting turn index or `null`. **Self-check** each
   `superseded-by`: object must be the newer decision. If unsure, drop it.
7. Unknown scalar → `null`; nothing-to-list → `[]`.

## Privacy

Submit only the distilled object — never raw dialogue. Decisions are recorded
in a git-tracked `BRAINPALACE_DECISIONS.md` digest the user can review. Only
runs for indexed projects with session indexing enabled.

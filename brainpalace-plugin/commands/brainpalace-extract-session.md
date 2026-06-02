---
name: brainpalace-extract-session
description: Extract durable knowledge from the current AI-coding session (summary, decisions, triplets) and submit it to BrainPalace
parameters:
  - name: session
    description: "Session id or path to the session JSONL (default: current session)"
    required: false
skills:
  - using-brainpalace
last_validated: 2026-05-30
---

# BrainPalace — Extract Session

## Purpose

Turn the chat session you just had into durable, searchable knowledge. This
command has **you, the model** read the session transcript, distil it into a
strict JSON object (summary + decisions + files + relationship triplets), and
submit it to the BrainPalace server via `brainpalace submit-session`.

No API spend beyond your existing subscription: the extraction runs inside this
runtime; the server only stores the result (it never calls an LLM). Works in any
runtime that supports markdown slash commands — Claude Code, Gemini CLI, Codex,
OpenCode.

This is the **manual** path. The same output contract is produced automatically
by the SessionEnd subagent (see `docs/SESSION_INDEXING.md`).

## Usage

```
/brainpalace:brainpalace-extract-session [<session-id-or-path>]
```

- **Claude Code:** with no argument, target the current session transcript at
  `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (the cwd path with `/`
  replaced by `-`).
- **Other runtimes:** pass the path to the session JSONL explicitly.

## What to do

1. **Locate + read** the session transcript JSONL.
2. **Reduce it mentally:** keep user/assistant text, condensed thinking,
   `tool_use` (name + key inputs like `file_path`/`command`), and truncated
   `tool_result`. Ignore queue-ops, attachments, and file-history snapshots.
3. **Produce ONE JSON object** matching the schema below. **Emit only the JSON**
   — no preamble, no markdown fence — when you pipe it to the CLI.
4. **Submit:**

   ```bash
   brainpalace submit-session <session_id> --json -    # then pipe the JSON to stdin
   ```

   (Write the JSON to a temp file and pass `--json <file>` if piping stdin is
   awkward in your runtime.)

## Extraction instruction block

You extract durable knowledge from a software-development chat session into a
single strict JSON object. You are given the session transcript and its metadata
(`session_id`, `project_path`, `branch`, `started_at`, `ended_at`).

The object MUST match this shape (no extra top-level keys):

```
{ session_id, project_path, branch, started_at, ended_at,
  summary, open_threads[],
  decisions[ {text, rationale, files[], supersedes} ],
  files_touched[ {path, action} ],
  tools_used[],
  triplets[ {subject, relation, object, evidence_turn} ] }
```

**Rules**

1. **Ground every claim in the transcript.** Never state a decision, summary
   sentence, or triplet the transcript does not support. When in doubt, omit.
   Empty arrays are correct — never invent content to fill them.
2. `summary`: ≤ ~120 words, plain past tense — what was actually accomplished.
3. `decisions`: real choices with consequences (design, tooling, approach).
   `rationale` = the stated why, or `null`. `files` = paths the decision
   concerns. `supersedes` = the text of a prior decision this one replaces, else
   `null`.
4. `files_touched`: from Edit/Write/Read tool uses. `action` ∈
   `{edit, create, read}`.
5. `tools_used`: distinct tool names observed.
6. `triplets`: relations from this **closed vocabulary only**, with these
   **directions** (subject → object):
   - `touches` — an edited/created file → the thing it implements.
     (`cache.py touches Redis cache backend`)
   - `fixed-by` — an error/bug → the fix or decision that resolves it.
     (`login 500 fixed-by token-expiry patch`)
   - `superseded-by` — an older decision → the newer one that replaces it.
     **`A superseded-by B` means B REPLACES A.**
   - `ran-in` — a tool/command → the session it ran in.
   - `depends-on` — a task/phase → its prerequisite.
   - `decided` — an actor/session → a decision it made.
   `evidence_turn` = the supporting turn index, or `null`.
   **Self-check:** before emitting each `superseded-by`, confirm the *object* is
   the newer decision and the *subject* is the one being replaced. If unsure,
   drop the triplet.
7. Unknown scalar → `null`; nothing-to-list → `[]`.

### Worked example (abbreviated)

Reduced transcript:
```
[turn 4] assistant: I'll switch the cache from in-memory dict to Redis so it
survives restarts. tool_use Edit(cache.py)
[turn 5] tool_result: edited cache.py
[turn 7] assistant: Bench shows the Redis path ~3x faster. tool_use Bash(pytest)
```

Output:
```json
{
  "session_id": "…", "project_path": "…", "branch": null,
  "started_at": null, "ended_at": null,
  "summary": "Switched the cache backend from an in-memory dict to Redis for restart durability and verified it with tests.",
  "open_threads": [],
  "decisions": [
    {"text": "Use Redis as the cache backend instead of an in-memory dict", "rationale": "survives restarts; ~3x faster in the run", "files": ["cache.py"], "supersedes": "in-memory dict cache"}
  ],
  "files_touched": [{"path": "cache.py", "action": "edit"}],
  "tools_used": ["Edit", "Bash"],
  "triplets": [
    {"subject": "cache.py", "relation": "touches", "object": "Redis cache backend", "evidence_turn": 4},
    {"subject": "in-memory dict cache", "relation": "superseded-by", "object": "Redis cache backend", "evidence_turn": 4},
    {"subject": "session", "relation": "decided", "object": "Use Redis as the cache backend", "evidence_turn": 4}
  ]
}
```

## Privacy

You submit only the distilled object — a summary, the decisions, and triplets —
not the raw dialogue. Decisions land in a git-tracked
`BRAINPALACE_DECISIONS.md` digest you can review. Submission is explicit: this
command runs only when you invoke it.

## Notes

- The server validates the payload strictly (closed relation vocabulary,
  `action` enum, no extra keys) and rejects malformed input — fix and re-run.
- Re-running for the same `session_id` overwrites that session's stored chunks
  and digest block (idempotent), so it's safe to re-extract.

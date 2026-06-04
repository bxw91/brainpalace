---
name: brainpalace-drain
description: Run one guarded drain of the session-summarization gap (opt-in, window-safe). Use inside a dedicated `claude --model haiku` + `/loop` babysitter, or by hand.
parameters:
  - name: empty-stop
    description: Self-terminate after N consecutive empty drains (default 3)
    required: false
skills:
  - using-brainpalace
last_validated: 2026-06-04
---

# BrainPalace Drain (opt-in, window-safe)

## Purpose

Run **one** guarded iteration of the free subagent summarization path without waiting
for your next real work prompt. Designed for an **opt-in babysitter**:

```
claude --model haiku
> /loop 5m /brainpalace-drain
```

It NEVER auto-runs. It only fires when you invoke it. It is:

- **mode-gated** — only the free `subagent` engine ever drains here;
- **single-drainer locked** — parallel worktrees / multiple babysitters dedup to one
  live drainer;
- **self-terminating** — stops after N consecutive empty drains so a `/loop` can never
  silently keep your Claude Code 5-hour usage window open.

> ⚠️ A running `/loop` is a model turn every interval, so it keeps your 5h window open
> while it runs. This command self-terminates after 3 empty drains; the loop ends then.
> It also dies on crash/close — with **zero data loss** (the gap is recomputed from the
> durable archive each run; backlog drains on your next real work turn regardless).

## Execution

1. Run the guarded iteration:

   ```bash
   brainpalace drain-tick --json
   ```

   (Pass `--empty-stop N` to override the self-terminate threshold.)

2. Parse the JSON result:
   `{status, drained, remaining, empty_streak, should_stop}`.

3. **If `status` is `skipped`, `locked`, or `no-project`, or `drained` is empty:**
   report one line (e.g. "Nothing to drain (status: locked).") and **do nothing else**.
   If `should_stop` is `true` and you are running inside a `/loop`, **end the loop now**
   (stop rescheduling).

4. **If `drained` is non-empty:** for each `session_id` in `drained`, dispatch the
   `chat-session-extractor` subagent (pinned to Haiku, free). It reads the transcript,
   distils it, and submits via `brainpalace submit-session` itself — only a short ack
   returns. Do this best-effort; do not block.

5. After dispatching, if `should_stop` is `true`, tell the loop to stop. Otherwise the
   next `/loop` tick will drain the next batch (`remaining` still pending in the gap).

## Old chats

Summarization is **archive-driven**: `drain-tick` summarizes the archived sessions that
still need it (new, resumed-and-grown, or unmarked, once quiescent) — OLD sessions are
picked up automatically as long as they were archived. No enqueue step is needed:

```bash
brainpalace backfill-sessions     # confirms archiving is on; drains do the rest
```

## Related

| Command | Description |
|---------|-------------|
| `brainpalace drain-tick` | The CLI iteration this command wraps |
| `brainpalace backfill-sessions` | Confirm archiving is on (drains summarize old transcripts) |
| `/brainpalace:brainpalace-extract-session` | Extract the CURRENT session on demand |

# Idea: time-driven session summarization via `/loop` (idle-but-open coverage)

> Status: **rough idea**, not a plan. Review, then convert to a real plan.
> Scope: the FREE subagent summarization path only (`mode: subagent`).

## Problem

Today summarization is **turn-driven**:

1. `SessionEnd` hook → appends ended `session_id` to `.brainpalace/extract-queue.txt` (durable).
2. `UserPromptSubmit` hook → `brainpalace drain-queue` (throttled: byte budget + count cap + 5-min cooldown) → injects a directive → the in-session model runs the `chat-session-extractor` subagent (Haiku, free on the Claude Code subscription) → `submit-session`.

Gap: if the session is **open but idle** (no new turns), nothing fires. A just-ended
session also waits for the *next* session's turn. The provider catch-up sweep used to
cover this server-side, but it is billable and now disabled by default.

Hard constraint: the **free** subagent path needs a **live CC session** — the server
can only run the billable provider engine. So "summarize while CC is closed" is
impossible for free, by design. This idea only targets **idle-but-open** + lower latency.

## Proposal (original)

- On first turn, start a `/loop` (5-min interval) that triggers summarization.
- Persist "last loop **started**" timestamp.
- New session, first turn: if last-started within 10 min → assume old loop alive → skip;
  else start a new 5-min loop.

## Flaw in the original guard

Start-time ≠ liveness. A `/loop` dies the instant its CC session closes. So:

> Session A starts loop 12:00, closes 12:02. Session B opens 12:05 → "started 5 min ago"
> → skips. Loop is dead → nothing summarizes until 12:10+. **Coverage gap.**

The guard must test **liveness**, not start-time.

## Improvements (what a real plan should adopt)

1. **Heartbeat, not start-time.** The loop writes `.brainpalace/extract-loop.heartbeat`
   on **every iteration**. A new session starts a loop only if the heartbeat is **stale**
   (> interval + slack, e.g. > 7 min for a 5-min loop). Correctly detects a dead loop.
   *(This is the single most important change.)*
2. **Atomic claim.** Two parallel sessions can both see "stale" and both start. Guard the
   start with an atomic lock (`mkdir` lockdir or `flock`) writing pid + ts. Prevents
   duplicate loops — matters with parallel worktrees / multiple open sessions.
3. **Self-terminate.** Stop the loop after N consecutive empty drains (~2–3×), else it
   pins a CC session alive forever (wasted subscription usage + odd UX). It restarts on
   the next `SessionEnd` that queues work.
4. **Reuse the existing throttle.** A loop iteration is just `brainpalace drain-queue`
   (already byte/count/cooldown bounded). Set loop interval ≥ cooldown. No new pacing.
5. **Mode gate.** Run only when `mode == subagent` (or `auto` with the plugin present).
   Skip in `provider` / `off`.
6. **Per-project.** Heartbeat + lock live under that project's `.brainpalace/`.

## Recommended architecture (opinion)

**Do not auto-start the loop inside the user's working session.** A loop reschedules the
model on a timer; interleaving it with the user's actual task is intrusive (risk: the
model wanders off draining instead of doing the user's work).

**Prefer a dedicated, opt-in babysitter:** `claude` running `/loop 5m /brainpalace-drain`
in a spare terminal. The plugin ships:
- a `/brainpalace-drain` command (one drain pass), and
- the **heartbeat + atomic-lock guard** so multiple babysitters and work sessions dedup
  to a single live drainer.

Work sessions stay clean; idle-time coverage is opt-in; closed-laptop still can't
summarize for free (honest limit).

## Open question to verify before planning (CC mechanics, not this repo)

Can a hook-injected instruction establish a **durable** `/loop` that survives interleaved
user turns? How do `/loop` vs `ScheduleWakeup` persist across turns and session close?
This is the riskiest assumption — confirm via the claude-code-guide before building.

## Rough scope sketch (for the future plan)

- New CLI: `brainpalace drain-queue` already exists; add a thin loop-target if needed.
- New plugin command: `/brainpalace-drain` (single pass; mode-gated; whoami-gated).
- Guard helper: heartbeat write + stale check + atomic lock, under `.brainpalace/`.
- Self-terminate counter + restart-on-queue.
- Docs + setup-surface parity (CLI · plugin · MCP) + CHANGELOG.

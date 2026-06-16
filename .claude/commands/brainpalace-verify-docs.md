---
description: Verify BrainPalace documentation prose against the live codebase and report drift (Layer B, repo-dev, advisory)
argument-hint: "[<doc path> | --changed | --all]  (default: --changed; go incrementally)"
allowed-tools: Bash, Read, Glob, Task
---

# Verify Documentation Prose (repo-dev)

Layer B of this repo's doc automation. Layer A (`sync-docs`) deterministically
generates and hard-gates the machine-owned facts; this verifies the **prose**
claims around them against the code, grounded by BrainPalace's own index. Judging
runs in-session on the subscription model — no metered API, no server-side LLM.

This is **repo-development tooling** (project scope, `.claude/`), not a shipped
plugin command. **Advisory, not a gate** — it surfaces drift (CONTRADICTED /
UNVERIFIABLE) for you to fix; it never rewrites prose or hard-fails a push.

## Run

Dispatch the **doc-verifier** subagent (`.claude/agents/doc-verifier.md`) via the
Task tool to run the procedure for `$ARGUMENTS` (default `--changed`).

**Model & dispatch (MANDATORY):** the doc-verifier is pinned to **Sonnet** in its
frontmatter so judging always lands on Sonnet **regardless of the active session
model** (Opus/Haiku/Sonnet). When dispatching, **do not pass a `model` override** —
let the agent's frontmatter pin win. **Never dispatch verification in parallel:**
one doc at a time, strictly sequential (resolve → judge → record → next). The
verdict cache makes sequential accumulation cheap; concurrent subagents only add
cold-start cost and are forbidden.

**Go incrementally — this is the normal mode.** Judging burns subscription
limits, so verify a **small bounded batch per run** (one doc, or a handful), then
stop and report. The verdict cache persists across runs (`claim+grounding`
verdicts are reused for free), so a few docs at a time **accumulates** to full
coverage without one big spend or a mid-run limit hit. `--all` is the heavy
exception — a deliberate full baseline only, and even then walk it in batches.

1. **Resolve the work packet** — the CLI does the deterministic half (affected-set
   resolution + prose extraction + cached verdicts):

   ```bash
   brainpalace verify-docs docs/FOO.md   # one doc — the normal, cheap case
   brainpalace verify-docs --changed      # done-boundary (net diff vs main)
   brainpalace verify-docs --all          # FULL baseline — heavy; walk in batches
   ```

   `--changed` computes the net diff vs `main` and adds **code-affected** docs via
   the index (a symbol moved in code, a doc still names the old one). Run *after*
   `sync-docs --fix` so Layer A regenerates facts first.

2. **Extract atomic claims** from each doc's `prose` (GENERATED blocks +
   frontmatter already stripped; narrative skipped).

3. **Reuse cached verdicts**, then **ground** each remaining claim:

   ```bash
   brainpalace query "<claim>" --mode multi --top-k 8 --json
   ```

4. **Judge** each claim → `SUPPORTED` / `CONTRADICTED` / `UNVERIFIABLE` (one
   batched pass per doc).

5. **Record** the verdicts; the CLI persists the cache, prints the drift report,
   and re-stamps `last_validated` for fully-clean docs only:

   ```bash
   brainpalace verify-docs --record -
   ```

## Output

A drift report listing, per doc, the CONTRADICTED and UNVERIFIABLE claims with
evidence (source + snippet). Clean docs (all SUPPORTED) are re-stamped and not
listed.

## Honest limits

- Advisory + probabilistic (LLM judge) — surfaces drift; a human resolves it.
- Code→affected-doc mapping is index recall, not 100% — misses are possible.
- Prose is never auto-*generated*, only verified. Layer A stays the only
  hard-gated half.

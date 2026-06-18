---
description: Verify BrainPalace documentation prose against the live codebase and report drift (Layer B, repo-dev, advisory)
argument-hint: "[<doc path> | --changed | --all] [--fix]  (weekly sweep: --all; before-push: --changed)"
allowed-tools: Bash, Read, Glob, Task, Edit, Write
---

# Verify Documentation Prose (repo-dev)

Layer B of this repo's doc automation. Layer A (`sync-docs`) deterministically
generates and hard-gates the machine-owned facts; this verifies the **prose**
claims around them against the code, grounded by BrainPalace's own index. Judging
runs in-session on the subscription model — no metered API, no server-side LLM.

This is **repo-development tooling** (project scope, `.claude/`), not a shipped
plugin command. **Advisory, not a gate** — by default it only surfaces drift
(CONTRADICTED / UNVERIFIABLE) and never hard-fails a push. The **verifier subagent
never rewrites prose** (read-only); prose fixes happen only in the opt-in `--fix`
phase below, driven by the orchestrator, never inside judging.

## Run

Dispatch the **doc-verifier** subagent (`.claude/agents/doc-verifier.md`) via the
Task tool to run the procedure for `$ARGUMENTS`.

**Invocation (repo-dev — don't memorize, it's here):** `verify-docs` is a
repo-development command that reads the `scripts/` freshness machinery, which is
NOT in the installed wheel — so the **installed `brainpalace` CLI refuses it**. Run
it from the source checkout: `cd brainpalace-cli && poetry run brainpalace
verify-docs …` (or `task`). The grounding queries (`brainpalace query …`) work
through the installed CLI too — only `verify-docs` is checkout-only. Tell the
dispatched subagent this so it doesn't trip the refusal.

**Two modes, two jobs — pick by intent:**
- **`--all` — the weekly sweep / periodic audit (default for a bare invocation).**
  The whole audited set, so it catches **latent drift already merged into `main`
  with no current diff** — which `--changed` structurally cannot. Kept cheap by
  `--skip-fresh` (default 6 days, re-judges only docs ≥6d stale) + the verdict
  cache; an all-fresh empty packet is normal. The weekly-sweep reminder invokes
  this mode.
- **`--changed` — the done-boundary / before-push gate.** Only the docs the
  current branch's diff touches (doc-edits ∪ code-moved-doc-stale via the index).
  This is what `verify-docs --check` enforces before push; explicitly pass it
  there.
- **`<doc path>` — one or more named docs.**

**Skip-fresh is ON by default in every mode** (`--skip-fresh N`, default **6
days**): a doc is skipped only when it was **already prose-verified** (has a
verdict-cache hit) **and** validated `< N` days ago **and** its content is
unchanged since (manifest-hash match), so a run never re-judges what's already
confirmed fresh — including a multi-doc explicit selection. A doc that was **never
prose-judged** — whose `last_validated` came only from the human audit
(`add_audit_metadata.py`), not from `--record` — is **never** skipped, even if
recent. A doc you **edited** since validation (changed hash) is always
re-verified, and
**`code-affected` docs** (a `--changed` index hit where the prose is unchanged but
the code it documents moved) are **never** skipped — skipping those would hide the
exact drift they surface. Disable per-run with `--skip-fresh 0`. (`--all` is still
the only mode that catches latent drift already merged into `main` with no current
diff; `--changed` structurally cannot.)

**Restart verification from scratch — `--reset`.** When you want the *whole*
audited set re-verified (criteria changed, distrust recent verdicts), run
`brainpalace verify-docs --reset`. It stamps today as a **baseline epoch** in
`.claude/.doc-verify-sweep.json`; from then on skip-fresh treats any doc validated
*before* the reset as stale, so subsequent sweeps re-judge the entire set
**incrementally** (draining across sessions — you can't audit everything in one
run). It mutates **no docs** and re-stamps nothing; a doc leaves the stale set
only when you actually re-verify it (its new `last_validated` lands on/after the
epoch). `--reset` is an action — it resolves no work packet.

**Model & dispatch (MANDATORY):** the doc-verifier is pinned to **Sonnet** in its
frontmatter so judging always lands on Sonnet **regardless of the active session
model** (Opus/Haiku/Sonnet). When dispatching, **do not pass a `model` override** —
let the agent's frontmatter pin win. **Never dispatch verification in parallel:**
one doc at a time, strictly sequential (resolve → judge → record → next). The
verdict cache makes sequential accumulation cheap; concurrent subagents only add
cold-start cost and are forbidden.

**Go incrementally — even for the `--all` weekly sweep.** Judging burns
subscription limits, so verify a **small bounded batch per run** (a handful of
docs), then stop and report. The verdict cache persists across runs
(`claim+grounding` verdicts are reused for free), so a few docs at a time
**accumulates** to full coverage without one big spend or a mid-run limit hit.
`--skip-fresh` makes resuming an `--all` sweep across sessions/days safe — docs
already verified in the window drop out, so you never re-judge what an earlier
batch covered.

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

   **Skip-fresh** (see "Skip-fresh is ON by default" above) is applied here too:
   recently-validated, unchanged docs drop out of the resolved set in every mode.
   The default **6-day** window sits **below** the 7-day weekly cadence (so last
   week's sweep is always re-verified this week) and **above** one sweep's multi-day
   span (so an `--all` sweep dragged across sessions/days never re-does docs an
   earlier batch already covered).

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
evidence (source + snippet) **and a `fix_tier`** per finding. Clean docs (all
SUPPORTED) are re-stamped and not listed.

## Fix drift (opt-in — only with `--fix` or when explicitly asked)

Default is report-only (advisory). When `--fix` is passed, after the drift report
is in hand, correct the prose **one doc at a time**. Doc prose fixes are nearly
always small text edits that the session model handles well, so:

1. **Default — fix INLINE in the main thread.** You already hold the drift report
   (each finding carries the correct value as `source` + snippet), so just apply
   the edits. This is the right call even when a *cheaper* model would suffice
   (e.g. Opus session, Sonnet enough): for a small edit a subagent's fixed
   cold-start (spin-up + re-read the file + re-derive the finding) costs more than
   the per-token premium you'd save, and the session model is never *weaker* than
   what a prose fix needs.

2. **Escape hatch — dispatch ONE fixer subagent** (`cavecrew-builder`) only when:
   - **bulky downgrade** — the doc's fix is large (a `moderate`/`hard` finding, or
     more than ~5 distinct edits) **and** a cheaper model than the session would do.
     Now `per-token-saving × volume > cold-start`, so dispatch at the cheaper model.
   - **upgrade** — the fix genuinely needs a *stronger* model than the session
     (rare for prose; e.g. a `hard` finding from a Sonnet session). Dispatch at the
     stronger model regardless of size — correctness over cold-start.

   The `fix_tier` per finding is the size/difficulty signal feeding this choice;
   there is no per-tier model table — prose is "Sonnet is enough" almost always.

3. **Fix all of a doc's findings in one pass**, using the evidence's correct value.
   Edit prose only — never touch GENERATED blocks (Layer A owns those).

4. **Re-verify the fixed doc** (`brainpalace verify-docs <doc>` → judge → record)
   so a now-clean doc gets re-stamped. Fixing is sequential per doc; the re-verify
   reuses cached verdicts for the untouched claims.

## Honest limits

- Advisory + probabilistic (LLM judge) — surfaces drift; a human resolves it.
- Code→affected-doc mapping is index recall, not 100% — misses are possible.
- Prose is never auto-*generated*, only verified. Layer A stays the only
  hard-gated half.

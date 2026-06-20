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
  relation-driven skipping (a fully-clean doc whose prose and grounded code are
  unchanged drops out) + the verdict cache; an all-fresh empty packet is normal.
  The weekly-sweep reminder invokes this mode.
- **`--changed` — the done-boundary / before-push gate.** Only the docs the
  current branch's diff touches (doc-edits ∪ code-moved-doc-stale via the index).
  This is what `verify-docs --check` enforces before push; explicitly pass it
  there.
- **`<doc path>` — one or more named docs.**

**Skipping is relation-driven — there is no time window.** A doc drops out of the
resolved set only while it is **already prose-verified** (verdict-cache hit), its
**authored prose is unchanged** (manifest-hash match), **every claim is clean**
(all SUPPORTED — code or `audit` tier), **and every grounded file/dir still hashes to the value stored at
record time**. Any change — edited prose, or moved code under a grounded path —
re-enters the doc automatically, so an idle repo costs nothing and there is no
staleness clock. A doc that was **never prose-judged** — whose `last_validated`
came only from the human audit (`add_audit_metadata.py`), not from `--record` — is
**never** skipped. **`code-affected` docs** (a `--changed` index hit where the
prose is unchanged but the code it documents moved) are **never** skipped —
skipping those would hide the exact drift they surface. (`--all` is still the only
mode that catches latent drift already merged into `main` with no current diff;
`--changed` structurally cannot.)

**Re-verify everything from scratch — `--all --force`.** When you distrust recent
verdicts or the judging criteria changed, `brainpalace verify-docs --all --force`
re-judges every audited doc, ignoring the relation-driven skip (it also works on a
named path: `verify-docs docs/FOO.md --force`). Still go in **bounded batches** —
`--force` overrides the skip, not the per-run budget; the verdict cache
accumulates across runs so coverage builds incrementally (you can't audit
everything in one run).

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
Relation-driven skipping makes resuming an `--all` sweep across sessions/days
safe — fully-clean docs with unchanged prose and grounded code drop out, so you
never re-judge what an earlier batch covered.

**Order the resume batch by drift, not by file order — "partial" is two
different states (MANDATORY).** A doc in the resolved packet ("partial" in the
`verify-docs --all` summary) is there for one of two unrelated reasons, and they
need opposite priority:
- **Recorded drift** — the doc carries cached **CONTRADICTED / UNVERIFIABLE**
  verdicts from an earlier run. These are the actionable backlog awaiting a prose
  `--fix`. **Do these FIRST**, biggest drift first.
- **Incomplete coverage** — the doc has only SUPPORTED verdicts (code- or `audit`-tier)
  but some claims are uncached or non-fresh (prose grew / earlier batch judged only a
  subset). Cheap to close, no known problem. **Do these SECOND.**

Do **not** assume "partial" means "had unresolvable issues, leave it last" — that
buries recorded drift. (Within a doc, code-vs-doc grounding order and doc-dep
settle are already handled automatically by the doc-verifier agent + CLI — see
`.claude/agents/doc-verifier.md`; you don't re-order for them here.) Inspect the
cache to bucket the packet before picking a batch (any cached verdict `!= SUPPORTED` →
recorded-drift bucket; `audit`-tier claims record as SUPPORTED, so they never show here):

```bash
brainpalace verify-docs --all 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); [print(sum(1 for c in x.get('cached_verdicts',[]) if c['verdict']!='SUPPORTED'),x['path']) for x in d['docs']]" | sort -rn
```

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

   **Relation-driven skipping** (see above) is applied here too: a fully-clean doc
   whose prose and grounded code are unchanged drops out of the resolved set in
   every mode. No time window — re-verification is triggered by an actual change
   (edited prose, or moved code under a grounded path), not a calendar, so an
   `--all` sweep dragged across sessions/days never re-does docs an earlier batch
   already covered, yet any real drift re-enters immediately.

2. **Extract atomic claims** from each doc's `prose` (GENERATED blocks +
   frontmatter already stripped; narrative skipped).

3. **Reuse cached verdicts**, then **ground** each remaining claim:

   ```bash
   brainpalace query "<claim>" --mode multi --top-k 8 --json
   ```

4. **Judge** each claim → `SUPPORTED` / `CONTRADICTED` / `UNVERIFIABLE` (one
   batched pass per doc). For an `unresolved` (no-code, no audited-doc-dep) claim in an
   **audit-fresh** doc the CLI keeps the verdict **SUPPORTED** on the **`audit` source
   tier** (`grounding_tier`) — a human-asserted external fact (benchmark/latency
   figures, third-party facts) the code can't verify, vouched by the freshness stamp.
   "External" is a *source*, not a status; it is clean, not drift, and CLI-derived.

   **Want to confirm a standing UNVERIFIABLE as human-verified?** That is a human
   authoring act (re-ground the prose off code if needed → re-stamp →
   re-sweep), not something this command does on its own. The step-by-step is in the
   `authoring-brainpalace-docs` skill → "Confirming an UNVERIFIABLE claim as
   human-verified".

5. **Record** the verdicts; the CLI persists the cache, prints the drift report,
   and re-stamps `last_validated` for fully-clean docs only:

   ```bash
   brainpalace verify-docs --record -
   ```

## Output

A drift report listing, per doc, the CONTRADICTED and UNVERIFIABLE claims with
evidence (source + snippet) **and a `fix_tier`** per finding. Clean docs (all
SUPPORTED — code or `audit` tier) are re-stamped and not listed; `audit`-tier claims
(human-asserted, vouched, no code referent) are surfaced only as a one-line count.

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

4. **Re-ground the fixed file IMMEDIATELY, before editing the next file
   (MANDATORY — one file at a time: edit → re-ground → next).** The moment a
   file's edits are done, re-verify it (`brainpalace verify-docs <doc>` → judge →
   record) so its now-clean claims are confirmed against code and it gets
   re-stamped — **only then** move to the next file. **Never batch the re-ground of
   several edited files to the end.** An edited-but-not-re-grounded file sits with
   **stale verdicts** (the cache still shows the pre-fix CONTRADICTED) and a stale
   content hash, which misreports drift that is already fixed on disk. Re-grounding
   reuses cached verdicts for the untouched claims, so per-file is cheap. This is
   the standing rule for any drift-fix pass, with or without `--fix`.

## Honest limits

- Advisory + probabilistic (LLM judge) — surfaces drift; a human resolves it.
- Code→affected-doc mapping is index recall, not 100% — misses are possible.
- Prose is never auto-*generated*, only verified. Layer A stays the only
  hard-gated half.

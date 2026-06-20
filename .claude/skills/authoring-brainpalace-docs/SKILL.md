---
name: authoring-brainpalace-docs
description: |
  Use when `brainpalace sync-docs --fix` reports PROSE-NEEDED, when a new
  command/skill/mode needs its human prose (Purpose, Examples) written, or when a
  human wants to mark a doc-verifier UNVERIFIABLE claim as human-confirmed.
  Authoring playbook for interface docs whose machine regions are generated.
license: MIT
last_validated: 2026-06-14
metadata:
  version: 1.0.0
allowed-tools:
  - Bash
  - Read
  - Edit
---

# Authoring BrainPalace interface docs

The deterministic generator owns the **machine regions** (frontmatter `parameters:`,
`GENERATED:*` blocks). You write the **human prose** only — never edit inside a
`GENERATED:` block.

## Flow
1. Run `brainpalace sync-docs --fix`. It regenerates machine regions and prints
   `PROSE-NEEDED: <id> -> <doc> (<reason>)` for anything that needs prose.
2. For each PROSE-NEEDED item, open the doc and write, **outside** any GENERATED block:
   - `## Purpose` — one short paragraph from `brainpalace <cmd> --help` (what it does,
     not why). Use only flags/behavior that actually exist.
   - `### Examples` — 1–3 real invocations.
3. Write prose **only where it is missing or dangling** — do not reword existing valid
   prose (keeps commits churn-free).
4. Re-run `brainpalace sync-docs --check` until it prints `doc-sync: OK`.

## Rules
- Never invent flags/commands/modes — verify against `--help` / `sync-docs --check`.
- Never edit inside `<!--GENERATED:…-->` blocks (the generator overwrites them).
- English only; match the surrounding docs' tone.

## Confirming an UNVERIFIABLE claim as human-verified

The doc-verifier fails closed: there is **no manual "mark confirmed" backdoor**. A
prose claim becomes human-confirmed only by reaching the **`audit` source tier** —
recorded `verdict: SUPPORTED, grounding_tier: audit` in
`scripts/doc_verify_cache.json`. The audit tier engages only when **both** hold:

1. The claim is **`unresolved` tier** — its grounding names **no code path** (a code
   path forces `code` tier, which audit can never override). A grounding that names
   only the host doc itself (self-ref) or an external/library fact is `unresolved`.
2. The host doc is **audit-fresh** — its current body hash matches
   `scripts/doc_freshness.json`, which only a human re-stamp
   (`scripts/add_audit_metadata.py`) can advance to a body holding an unresolved
   claim. This sidecar manifest — **not** the cache, **not** the frontmatter
   `last_validated` date — is the authoritative "audited by human" record checked on
   every future sweep (`_doc_audit_fresh` in `verify_docs.py`).

So a code-grounded UNVERIFIABLE claim (e.g. a library default our code never sets)
cannot be confirmed as-is. **Re-ground the prose** so it reads as an external fact
("the `bm25s` library default, not overridden by BrainPalace"), turning a checkable
"not overridden" assertion into either a `code` SUPPORTED or an `unresolved`→`audit`
SUPPORTED.

### One-step order — `verify-docs --confirm <doc>…` (preferred)

A human "mark verified" is a **complete, durable order**, not a multi-command chore.

```bash
cd brainpalace-cli && poetry run brainpalace verify-docs --confirm <doc>…
```

It writes the order to the durable **confirm ledger**
(`scripts/doc_verify_confirmed.json`, keyed by claim-hash, recording
`{doc, claim, grounding, confirmed_by, confirmed_at}`) and re-settles in the same
call, so the doc's open **external** claims flip `SUPPORTED` / `grounding_tier:
audit` and clean docs re-stamp **immediately** — no separate `add_audit_metadata.py`
re-stamp, no follow-up sweep. The ledger is **separate from the verdict cache**, so a
later `--record` sweep can never erase the order: `_derive_record` re-consults it on
every run (`_claim_confirmed`). The order persists the instant it is given.

**Scope (enforced):** only an `unresolved` claim (no code path, no audited-doc dep)
is confirmable. A `code` / `doc-dep` claim is **refused** — code stays ground truth.

> **The cache verdict is NOT the doc — read the live prose before prescribing a fix.**
> A cached `code`-tier UNVERIFIABLE can be **stale**: the prose may already have been
> re-grounded to an external fact while the recorded grounding still names a code path.
> Tier is derived from the *recorded grounding string*, which lags the prose until the
> next sweep. So when `--confirm` refuses a claim: open the doc. If the prose is
> already external ("the `bm25s` library default, not overridden by BrainPalace"), the
> grounding is stale — **re-sweep** the doc (the agent re-grounds it, usually →
> SUPPORTED `code` tier: our code not setting the value *is* the confirmation). Do
> **not** re-prose. Only re-prose when the prose genuinely still names our code.

### Whole-doc alternative — manual audit re-stamp
The older path still works and is right when you are vouching for a doc's whole body
(not one claim): re-ground if needed → `sync-docs --fix` → `python
scripts/add_audit_metadata.py <doc>…` (re-stamp the **final** body; doing it before
`sync-docs` is a trap — a later GENERATED rewrite breaks audit-freshness) →
`/brainpalace-verify-docs --changed` (the sweep is the only step that writes the
cache). The manifest re-stamp (`_doc_audit_fresh`) and the confirm ledger are two
independent vouch signals — either promotes an `unresolved` claim.

A sibling CONTRADICTED claim in the same doc does **not** block confirmation —
promotion is per-claim — but the doc stays not-fully-clean until that real drift is
fixed too.

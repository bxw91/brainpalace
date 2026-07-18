---
last_validated: 2026-07-18
---

# Retrieval Evaluation Harness

A repeatable, offline way to measure **retrieval quality** so any change that
touches indexing or query can be shown to improve results instead of shipping
on vibes. It builds a throwaway index over a small committed corpus, runs a set
of query cases, and scores the returned sources with rank-based metrics
(recall@k, MRR) against a committed baseline.

> **Directional, not pass/fail.** The harness is **not** part of `task
> pr-qa-gate`. Retrieval scores are noisy and provider-dependent; gating CI on
> them would cause flaky failures. It is a tool you run when changing retrieval,
> and a baseline that makes regressions visible in review.

## TL;DR

```bash
# from the repo root
task eval                    # run all cases, diff vs baseline.json
task eval -- --json          # machine-readable output
task eval -- --strict        # non-zero exit if a metric regressed
task eval -- --update-baseline   # refresh the snapshot (explicit; needs a reason)
```

Requires `OPENAI_API_KEY` — see [Provider & determinism](#provider--determinism).

## What it measures

For each case (`tests/eval/cases.yaml`) the harness retrieves the top-`k`
sources for a query in a given mode and scores them against the **expected**
source path suffixes:

- **recall@k** — fraction of a case's expected sources found in its top-k.
- **reciprocal rank** — `1 / rank` of the first expected hit (0 if none); the
  mean over cases is the familiar **MRR**.
- **mode-agreement** — informational: did `hybrid` fusion beat raw `bm25` MRR on
  the overlapping cases?

Metrics are **rank-based over stable source identifiers**, so they don't wobble
when raw embedding scores drift slightly between runs.

## Layout

| File | What |
|------|------|
| `brainpalace-server/tests/eval/corpus/` | small committed fixture corpus (authored so expected hits are knowable) |
| `brainpalace-server/tests/eval/cases.yaml` | the query cases |
| `brainpalace-server/tests/eval/runner.py` | builds a temp index, runs cases through the real `/index` + `/query` path |
| `brainpalace-server/tests/eval/scorer.py` | recall@k, MRR, mode-agreement (pure functions) |
| `brainpalace-server/tests/eval/report.py` | table + JSON output, baseline diff |
| `brainpalace-server/tests/eval/baseline.json` | committed score snapshot |
| `brainpalace-server/tests/eval/test_scorer.py` | scorer unit tests (key-free, in the normal suite) |
| `brainpalace-server/tests/eval/test_eval_smoke.py` | opt-in end-to-end smoke (see below) |

The runner drives the **real** server in-process via FastAPI `TestClient` — same
indexing, embedding, BM25, and fusion code a user hits, no mocks. The index
lives in a fresh temp `BRAINPALACE_STATE_DIR` and is torn down after the run; it
never touches a real state dir.

## Adding a case

Append to `tests/eval/cases.yaml`:

```yaml
- id: my-new-case           # unique, short
  query: "the search text"
  mode: hybrid              # bm25 | vector | hybrid
  k: 3                      # top-k to retrieve and score
  expected: ["auth.md"]     # source-path SUFFIXES, matched with str.endswith
```

Keep `expected` to the clearly-correct file(s). If the topic isn't in the
corpus, add a small file under `tests/eval/corpus/` whose content you control,
then add the case. After a change that legitimately moves scores, refresh the
baseline (below) with a written reason.

## Reading the scores

```text
mode        cases  errors   recall@k     mrr
------------------------------------------------------------
bm25            5       0      1.000   1.000
hybrid          6       0      1.000   1.000
vector          5       0      0.900   1.000
------------------------------------------------------------
OVERALL        16       0      0.969   1.000
```

`recall@k` near 1.0 means the expected files are being retrieved; `mrr` near 1.0
means they're at the top. `errors > 0` means a case raised (e.g. a query failed)
— those score zero. Below the table, any cases that didn't hit are listed.

## Baseline & regressions

`task eval` (which runs `report.py --baseline`) diffs the run against
`tests/eval/baseline.json` and flags:

- any overall or per-mode `recall@k` / `mrr` that dropped more than the epsilon
  (`0.02`), and
- any case that flipped from **hit → miss** (the sharpest signal of a real
  break).

`--strict` turns a flagged regression into a non-zero exit (useful when you want
a hard local check); the default is directional and exits 0.

### Refreshing the baseline — legitimately vs. masking

Refreshing is **explicit** and **manual**:

```bash
task eval -- --update-baseline
```

A baseline refresh is legitimate when scores moved for a known, reviewed reason:
you added/changed cases, changed the corpus, or made a retrieval change you've
confirmed is an improvement. **State the reason in the commit message.** Never
rubber-stamp `--update-baseline` to make a red diff go away — that hides the
exact regression the harness exists to catch.

## Provider & determinism

The eval pins **OpenAI `text-embedding-3-small`** as the embedding model (the
only live provider in this dev/CI environment). A baseline is **only comparable
under the same model** — `report.py` flags a model mismatch in the diff. The
runner writes a temp `config.yaml` pinning both the embedding and summarization
providers to OpenAI so indexing constructs without an Anthropic key (eval never
generates summaries, but the provider is still built). Set `OPENAI_API_KEY`
before running.

`vector` and `hybrid` modes need real embeddings (a key); `bm25` is keyword-only
but indexing the corpus still generates embeddings, so the whole harness needs a
key in practice. Graph/multi modes are deferred to later phases.

## Tests in the suite vs. opt-in

- `test_scorer.py` runs in the normal suite and `pr-qa-gate` — it's key-free and
  covers all the metric logic.
- `test_eval_smoke.py` is the end-to-end integration smoke. It needs a real key,
  but the shared test config force-sets a dummy `OPENAI_API_KEY` and caches
  providers, so it runs the harness in a **subprocess** with a clean env and is
  **opt-in**:

  ```bash
  BRAINPALACE_EVAL_OPENAI_KEY="$OPENAI_API_KEY" \
      env -u VIRTUAL_ENV poetry run pytest tests/eval/test_eval_smoke.py
  ```

  Without that variable it skips, so `pr-qa-gate` stays green and key-free.

## Two validation layers (Phase 160)

Retrieval-affecting phases are validated at two levels, because the recall
harness above (fresh-index, OpenAI-embedding, `ENABLE_GRAPH_INDEX=false`) can
only measure document/graph **recall** — it structurally can't exercise
time-sensitive or session-graph behaviour (a freshly-indexed chunk has
`created_at≈now`, so time-decay is inert; supersession needs `/sessions/extract`
state; LSP needs a server).

**1. Keyless end-to-end suite — `tests/validation/`, runs in `pr-qa-gate`.**
Drives the *real* `GraphStoreManager(sqlite)`, `GraphIndexManager`,
`SessionExtractService`, `session_linker`, and `QueryService` ranking methods
with controlled inputs (fake embedder/store; real graph + real ranking). Proves:

- `test_graph_pipeline.py` — graph build → GRAPH query → reopen-persist
  (090/100).
- `test_supersession_pipeline.py` — two sessions where B supersedes A → A's
  facts invalidated (history edge preserved) → stale-decision penalty re-ranks
  (060+090+100+140).
- `test_ranking_composition.py` — time-decay + stale penalty compose in
  `execute_query` order (110+140).

No API key; always on.

**2. Graph-recall corpus cases — opt-in, OpenAI.** `tests/eval/cases_graph.yaml`
holds `graph`-mode cases; run them with the graph index enabled:

```bash
env -u VIRTUAL_ENV poetry run python -m tests.eval.runner --graph
```

`--graph` sets `ENABLE_GRAPH_INDEX=true` so the index job builds the knowledge
graph, then appends the graph cases. Not part of the default scored baseline.

**LSP (150)** is validated by the server-gated `tests/lsp/test_live_pyright.py`,
which **skips** when no language server is installed — so multi-language live
coverage requires installing the servers (`BRAINPALACE_LSP_LANGUAGES`).

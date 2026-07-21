---
last_validated: 2026-07-21
---

# Releasing BrainPalace

CalVer `YY.M.N` (2-digit year · month · Nth release that month). `brainpalace-cli`,
`brainpalace-rag` (server), and `brainpalace-dashboard` (web control plane)
**release in lockstep at the same version**.

## Branch model (maintainer)

- **`stable`** is the active development branch and is **LOCAL-ONLY — never push it.**
  The full development history (hundreds of commits) lives only on the maintainer's
  local `stable`; don't rebase it away.
- **`main`** is the only remote branch: the squashed, published mirror — one commit per
  release, carrying `stable`'s curated tree. All public clones see `main`.
- Remote: `brainpalace` → github.com/bxw91/brainpalace.
- Releases are cut on `main` (see below), not by pushing `stable`.

## How publishing works — read this first

**PyPI publishing is automated.** The `.github/workflows/publish-to-pypi.yml`
workflow fires `on: release: published` and uploads all three packages in
dependency order — **server first, then cli, then dashboard** (the cli depends
on the server; the dashboard depends on the cli) — using a **PyPI Trusted
Publisher (OIDC)** — short-lived, repo-scoped, **no API token**. Each package
publishes from its own GitHub environment: `pypi`, `pypi-cli`, and
`pypi-dashboard`.

> **Dashboard SPA is built in CI, not committed.** The dashboard's built SPA
> (`brainpalace_dashboard/static/`) is gitignored generated output — it is no
> longer committed to git (committing content-hash-named build output churned the
> worktree on every rebuild). The `publish-dashboard` job sets up Node and runs
> `npm ci && npm run build` before `poetry build`; pyproject's `[tool.poetry]
> include` force-packages the freshly built `static/` into the wheel + sdist, so
> end users still `pip install brainpalace-dashboard` and get a prebuilt SPA with
> no node toolchain. Locally the same build runs via `task install`,
> `task install:from-source`, and `task build:dashboard-ui`.

> **One-time setup for `brainpalace-dashboard`:** the dashboard package needs its
> own PyPI Trusted Publisher and a matching GitHub environment named
> `pypi-dashboard` before the first dashboard release. On PyPI: add a Trusted
> Publisher for project `brainpalace-dashboard` → repo `bxw91/brainpalace`,
> workflow `publish-to-pypi.yml`, environment `pypi-dashboard`. In GitHub repo
> Settings → Environments, create `pypi-dashboard`. Until this exists, the
> `publish-dashboard` job fails (and your editor flags the unknown environment).

- **Do NOT run `poetry publish` by hand.** A manual upload bypasses the Trusted
  Publisher, trips a PyPI security warning, and makes the workflow's own publish
  step fail on the now-duplicate files (PyPI uploads are immutable). Creating the
  GitHub Release *is* the publish trigger.
- No PyPI API token is needed anywhere — locally or in CI. If one exists in
  `~/.config/pypoetry/auth.toml` or your PyPI account, delete it.

## Version: one source of truth

The version lives in **one place per package**: `pyproject.toml`.

- `brainpalace_cli/__init__.py` and `brainpalace_server/__init__.py` derive
  `__version__` from installed package metadata
  (`importlib.metadata.version(...)`) — **do not** hardcode a version string
  there. `__version__` feeds `--version` for both CLIs *and* the server's HTTP
  surface (`/health`, `/runtime`, OpenAPI).
- Because `__version__` reads metadata, **editable dev installs only reflect a
  new version after reinstall** (`task install`, or `pipx install` for the
  global CLI). Built wheels always carry the correct version straight from
  `pyproject.toml`, so published artifacts are never wrong — this is the
  guarantee that matters.
- `tests/test_version_consistency.py` (cli) fails the gate if the two
  `pyproject.toml` versions drift apart.
- The publish workflow also re-checks that the release **tag** matches both
  `pyproject.toml` versions before uploading.

## Release checklist

> **One-command local prep.** Steps 3–8 (the LOCAL, reversible half — version
> bump across all six sites, changelog roll, reinstall, doc-freshness re-stamp,
> and the full `before-push` gate) are automated by
> **`task release:prep -- <YY.M.N>`** (e.g. `task release:prep -- 26.7.2`). It
> sets `BRAINPALACE_RELEASE=1` for you so the siblings resolve to local source
> and the gate is allowed to run. Land your work on `stable` (step 1), pick the
> version (step 2), run that one task, then do the outward-facing steps 9–13 by
> hand (commit, mirror to `main`, tag, create the GitHub Release). The
> per-site/per-step detail below stays authoritative — read it to understand what
> the task does or to run a step manually. Under the hood it calls
> `scripts/bump_version.py` (six version sites) and `scripts/roll_changelog.py`
> (Unreleased → versioned section), both guarded by
> `brainpalace-cli/tests/test_version_consistency.py`.

1. **Land all work on `stable`** and get `task before-push` green
   (`export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` first, or
   Poetry dies on the headless keyring).
2. **Pick the version** — check `git tag` for the latest `vYY.M.N`; increment N
   within the month (resets monthly).
3. **Bump `version` in all three** `brainpalace-cli/pyproject.toml`,
   `brainpalace-server/pyproject.toml`, **and** `brainpalace-dashboard/pyproject.toml`
   — plus the dashboard's hardcoded `brainpalace_dashboard/__init__.py`
   `__version__` (the dashboard does **not** derive it from metadata) — **and the
   Claude Code plugin**: `brainpalace-plugin/.claude-plugin/plugin.json` `version`
   **and** the `plugins[0].version` entry in `.claude-plugin/marketplace.json`.
   The plugin tracks cli/server in lockstep **regardless of whether plugin files
   changed** — `plugin.json`'s `version` is the freshness key that drives Claude
   Code plugin-update detection (`brainpalace plugin status` / the `update` tail
   read the manifest at the latest release tag), so a frozen field means the
   user is never offered `claude plugin update`. The cli + server derive
   `__version__`, so nothing else needs touching there. The
   `test_version_consistency.py` guard enforces all three pyprojects, the
   dashboard `__version__`, **and** the plugin manifest + marketplace entry moved
   together.
4. **Reinstall** so editable `--version` reflects the bump: `task install`.
5. **Changelog** — entries accumulate under `## [Unreleased]` between releases
   (**never hand-number an unreleased section** — the next version is unknown until
   you cut it). At release, **rename `## [Unreleased]` → `## [YY.M.N] - DATE`** and
   insert a fresh empty `## [Unreleased]` above it, so the next between-release commit
   has a bucket and can't invent a guessed version header. Keep each entry ≤ 3
   sentences (see [DEVELOPERS_GUIDE.md → Changelog style](DEVELOPERS_GUIDE.md#changelog-style-docschangelogmd)).
6. **Refresh doc freshness** — any audited doc whose content changed this
   release must be re-read against the code and re-stamped. List stale docs with
   `python scripts/check_doc_freshness.py`; after re-reading, stamp them
   (`python scripts/add_audit_metadata.py <paths>` re-stamps `last_validated` to
   today + re-records the hash in `scripts/doc_freshness.json`). The gate in step 8
   enforces this — a doc whose authored content no longer matches its manifest
   hash fails the build. The rule's meaning lives in [DEVELOPERS_GUIDE.md](DEVELOPERS_GUIDE.md#documentation-freshness-last_validated).

   > **Always pass explicit paths — a bare `add_audit_metadata.py` re-stamps
   > EVERY audited doc.** `last_validated` means "a human confirmed this against
   > the code today"; blanket-stamping asserts that for docs nobody read this
   > release, which is a false attestation and destroys the signal the field
   > exists to carry. Stamp only what you actually re-read:
   > `python scripts/add_audit_metadata.py docs/CHANGELOG.md docs/MCP_SETUP.md`.
   > Targeting also preserves every other doc's manifest entry instead of
   > rebuilding the whole manifest. If you blanket-stamp by accident, revert the
   > stamp **per file** — a wide `git checkout -- docs/ scripts/ …` also throws
   > away the changelog roll and version-bump sites, and the loss is silent.
7. **Dashboard parity** — confirm every new config option / CLI command /
   server endpoint this release is surfaced in the control-plane dashboard or
   allowlisted with a reason. Enforced by `task lint:dashboard-parity` (part of
   the step-8 gate); the rule lives in
   [DEVELOPERS_GUIDE.md](DEVELOPERS_GUIDE.md#dashboard-parity-surface-every-feature).
   - [ ] `task before-push` green (includes `lint:dashboard-parity`) — every new
         config/CLI/endpoint is surfaced in the dashboard or allowlisted.
7b. **Layer B prose verification (marker gate).** `before-push` now runs
   `lint:doc-verify`, which fails unless the doc-verifier was run for THIS
   release's diff — so count/config prose drift can't accumulate unseen across
   releases. It never blocks on an LLM verdict, only on "was it run". Before the
   gate, in a Claude Code session run `/brainpalace-verify-docs --changed` (or
   dispatch the doc-verifier agent): it judges the affected docs and records the
   per-diff marker. The net-diff base is the previous `release:` commit (not
   `main` — `stable`/`main` have unrelated histories). Broader latent drift in
   docs this release didn't touch stays on the WEEKLY `--all` sweep.

   > **Steps 5–8 are a LOOP, not a line — verify LAST.** The marker keys on the
   > current diff, so *any* doc write invalidates it: the changelog roll (step 5),
   > a freshness re-stamp (step 6), or a prose fix the step-8 gate itself demands
   > (`lint:changelog` style caps, `lint:doc-freshness`). Each invalidation costs
   > a full doc-verifier pass. Land **every** doc edit first, then verify, then
   > gate — and whenever a gate failure sends you back to edit a doc, re-run the
   > verifier before the next gate attempt. Budget for this: a release that
   > touches changelog prose needs the verifier at least twice.
   - [ ] `/brainpalace-verify-docs --changed` run; per-diff marker recorded.
8. **Gate**: `task before-push` must exit 0 — read that status **directly**
   (`BRAINPALACE_RELEASE=1 task before-push; echo "EXIT=$?"`), never through a
   pipe. `task before-push | tail -40` reports *`tail`'s* status, so a red gate
   reads green and you publish on a failing build. Redirect to a log and grep it
   instead. **Necessary, not sufficient** — the
   `publish-to-pypi.yml` workflow re-runs the gate (`task test`) in a *pristine
   CI env* that has **no Claude Code plugin installed** and may resolve a
   different Click version. So a test whose behavior depends on the host
   (plugin presence, or `click.confirm`/`prompt` returning a default vs aborting
   on exhausted stdin) can pass `before-push` locally yet **fail the release
   workflow's gate** — which blocks the publish (see step 12's gate-vs-publish
   distinction). Before cutting the release, sanity-run the interactive
   wizard/init tests as CI sees them — mock `claude_plugin_installed` to `False`
   (CI has no plugin) — and fix any test that relies on EOF-default stdin
   behavior by answering *every* prompt explicitly. Interactive tests should mock
   `claude_plugin_installed` and the port scan (`_find_available_api_port`) so
   they are host-independent.
   - **Dashboard-absent coupling (same trap).** The 3.11 CLI gate has **no
     dashboard installed**, so CLI code must not `import brainpalace_dashboard`
     in a call/render path (probe via `dashboard_status_info()`), and CLI tests
     for dashboard-aware output must mock that seam — never assume the package
     imports. See [DEVELOPERS_GUIDE.md → CLI ↔ dashboard import boundary](DEVELOPERS_GUIDE.md#cli--dashboard-import-boundary-the-dashboard-is-optional).
     `task release:rehearse-ci` (step 8a) now import-blocks the dashboard for the
     cli/server suites, so this fails locally instead of in CI.
   - **Local-sibling gate — automatic under `BRAINPALACE_RELEASE=1`.** The cli pins
     `brainpalace-rag`/`brainpalace-dashboard` by PyPI version, and the *previous*
     release is already published — so a plain cli install resolves the **old**
     sibling. Any endpoint / module / config field **added this release** would then
     read as false drift in the dogfood + doc-sync tests (they reflect docs against
     the LIVE installed server+dashboard), false-failing the gate. Because the gate
     is run with `BRAINPALACE_RELEASE=1` (already required by the before-push
     guard), `cli:install` now force-switches the siblings to **local path deps**,
     builds the cli venv against local source, and **restores `poetry.lock`** after
     — so the gate tests THIS release while the committed lock stays PyPI-pinned
     (step 12 refreshes it after publish). No manual path-dep juggling needed.

     > **The publish workflow's own gates need this too — do not remove it.**
     > `publish-to-pypi.yml`'s **Quality Gate** and **Dashboard Gate** jobs set
     > `BRAINPALACE_RELEASE=1` job-wide for the same reason: at gate time this
     > release's server/dashboard are **not on PyPI yet** (they upload later in the
     > same run), so any `task install` — including the one `cli:test` triggers via
     > `deps: [install]`, which otherwise clobbers a manual path-install — must
     > build against local sibling source. 26.7.2 first failed exactly here: the
     > gates installed the previous (narrower) server and the query-mode import
     > guard / parity check tripped on drift. If you ever add a step that installs
     > siblings in those jobs, keep it under `BRAINPALACE_RELEASE=1`.

   - **Widening a shared enum (or any runtime guard vs the installed server) is a
     server-first, same-release change.** The MCP `QueryMode` Literal is *derived
     from and guarded against* the server enum (it `raise`s on drift at import).
     So adding a query mode (or similar cross-package enum widening) means the CLI
     is momentarily **ahead** of the published server: it MUST ship in the same
     release, server-first (the publish job already waits for `brainpalace-rag` on
     PyPI before the cli), and the gates MUST run against local source (bullet
     above) — never let the cli reach users ahead of a matching server, or
     `brainpalace mcp` hard-fails on the version skew.

   **8a. Dashboard-absent CI rehearsal — now automatic.** The 3.11 publish/PR-QA
   quality gate runs in a **server+cli env with no dashboard installed** (the
   dashboard's `python = ">=3.12"` marker excludes it, and its venv is absent), so
   a doc-sync checker or wrapped gate that needs the dashboard could pass
   `before-push` yet fail there. `task before-push` now runs `task
   release:rehearse-ci` for you — it forces that env (`BRAINPALACE_DOCSYNC_NO_DASHBOARD`
   + a `sitecustomize` import-blocker) and re-runs `lint:docs-gates-ci` + server &
   cli tests as CI does, so step 8 already covers this. The flip side is validated
   too: the publish/PR-QA workflows now include a **Dashboard Gate** job (Python
   3.12, all three packages installed) that runs the FULL `lint:doc-sync` +
   `lint:dashboard-parity` with the dashboard present, and publishing waits on it.
9. **Commit on `stable`** (version bump + changelog).
10. **Mirror to `main`** and tag. **`stable` is LOCAL-ONLY — NEVER `git push` it.**
   `main` is the only remote branch: a single squashed commit per release that
   mirrors `stable`'s (already curated) tree. Releases are cut on `main`, not by
   pushing `stable`.
   ```bash
   git checkout -B main brainpalace/main
   git read-tree --reset -u stable        # main tree := stable tree
   git commit -m "BrainPalace YY.M.N"     # single squashed commit
   git tag -a vYY.M.N -m "BrainPalace YY.M.N"
   git push brainpalace main && git push brainpalace vYY.M.N
   git checkout stable
   ```
   The published tree is curated *on `stable`* (e.g. `docs/superpowers` planning
   docs are untracked there), so `read-tree --reset stable` mirrors the right
   tree — do not hand-pick files.

   > **`main` is a protected branch — no force-push, no rewriting a pushed
   > commit.** The plain `git push` above is a fast-forward (new commit on top of
   > `brainpalace/main`), which is fine. But if a release commit is already on
   > `main` and you need to correct it (e.g. the gate-fix recovery in step 12),
   > you **cannot** reset + `--force`: the protected-branch hook rejects it. Land
   > the correction as a **forward commit** instead — `git checkout -B main
   > brainpalace/main && git read-tree --reset -u stable && git commit -m
   > "BrainPalace YY.M.N: …"` — so `main` HEAD's tree again equals `stable`, at
   > the cost of one extra commit for that release. Then move the tag (delete +
   > recreate) onto the new HEAD.
11. **Create the GitHub Release — this publishes to PyPI:**
   ```bash
   gh release create vYY.M.N --repo bxw91/brainpalace \
     --title "BrainPalace YY.M.N" --notes-file <notes>
   ```
   The `publish-to-pypi.yml` workflow runs the quality gate, then publishes
   `brainpalace-rag` and `brainpalace-cli` via OIDC (it waits for the server to
   appear on PyPI before publishing the cli). **Do not publish manually.**
12. **Verify the run is green** and both versions are live:
    ```bash
    gh run list --repo bxw91/brainpalace --workflow publish-to-pypi.yml --limit 1
    curl -s https://pypi.org/pypi/brainpalace-rag/json | python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])'
    curl -s https://pypi.org/pypi/brainpalace-cli/json | python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])'
    curl -s https://pypi.org/pypi/brainpalace-dashboard/json | python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])'
    ```
    **Two distinct failure modes — do not conflate them:**
    - **The publish *step* failed** (a wheel was already uploaded, or partially):
      that PyPI version is burned — a version can never be re-uploaded. Fix the
      cause and ship a new patch `N+1`.
    - **The *gate* failed before any upload** (the workflow's `task test`/lint
      step is red, so the publish jobs never ran): **nothing reached PyPI, so the
      same version is reusable.** First confirm with the step-12 `curl`s that all
      three packages are still at the *previous* version, then recover in place:
      ```bash
      # nothing published → reuse YY.M.N
      gh release delete vYY.M.N --repo bxw91/brainpalace --yes --cleanup-tag
      git tag -d vYY.M.N                       # drop the local tag too
      # fix the cause, commit on stable, re-run before-push green
      # re-mirror as a FORWARD commit (main is protected — see step 10):
      git checkout -B main brainpalace/main
      git read-tree --reset -u stable
      git commit -m "BrainPalace YY.M.N: <gate fix>"
      git push brainpalace main                # fast-forward, NOT --force
      git tag -a vYY.M.N -m "BrainPalace YY.M.N" && git push brainpalace vYY.M.N
      git checkout stable
      gh release create vYY.M.N --repo bxw91/brainpalace \
        --title "BrainPalace YY.M.N" --notes-file <notes>   # re-fires publish
      ```
13. **Refresh the cli lock** so the committed lock and local cli-from-source
    builds pull the matching server **and dashboard**: `(cd brainpalace-cli &&
    poetry update brainpalace-rag brainpalace-dashboard --lock)`, then commit on
    `stable`. The cli depends on **both** `brainpalace-rag` and
    `brainpalace-dashboard` by PyPI version (not a local path), so `task install`
    for the cli installs whatever the lock pins — without this step a
    cli-from-source dev env keeps the *previous* server **and dashboard** release.
    The pins stay `^YY.M.1`; only the lock entries move. Run it **after** step 12
    confirms the new version is live on PyPI.

    > **Refresh `brainpalace-dashboard` too — not just the server (regression
    > guard).** The cli lock pins the dashboard as well, and it is consumed by the
    > `tests/doc_sync/` **dogfood** tests, which import the LIVE dashboard
    > (`brainpalace_dashboard.ui_schema`) and reflect it against the LIVE cli
    > `config_schema`. If only `brainpalace-rag` is refreshed each release, the
    > dashboard pin silently rots: a later cli refactor that renames/drops a
    > `config_schema` symbol the *old* pinned dashboard still imports (e.g. the
    > `API_KNOWN_FIELDS` → bind-section removal in `62a1d8c2`) makes those dogfood
    > tests fail in `task before-push` `test:cov` with an `AttributeError` from
    > `ui_schema.py` — and the failure surfaces a release or more *later*, far from
    > the refactor. The publish workflow's **Dashboard Gate** (Py 3.12, all three
    > packages at the new release) is immune because it installs the freshly-built
    > dashboard, so this gap is *local-gate-only* and easy to miss. If you hit it
    > mid-release, refresh the pin to the latest published-compatible dashboard
    > (`poetry update brainpalace-dashboard` in `brainpalace-cli`) and re-run the
    > gate; commit the moved lock entry with the release. (Poetry caches the index — if version solving fails because it can't
    see the new release even though it's live on PyPI's simple index, the stale
    entry is the **repository cache**, not just `_http`. `poetry cache clear --all
    pypi` does **not** clear it — the source key is `PyPI` (capitalized), so that
    command reports "No cache entries for pypi" and changes nothing. Nuke the
    whole dir: `rm -rf ~/.cache/pypoetry/cache ~/.cache/pypoetry/_http`, then
    re-run `poetry update brainpalace-rag --lock`. The cycle that breaks: dashboard
    `YY.M.N` pins cli `==YY.M.N`, so until cli `YY.M.N` is visible the resolver
    discards dashboard `YY.M.N` and falls back to the previous dashboard, which
    conflicts with the local cli at the new version.)

## Environment gotchas

- `VIRTUAL_ENV=/usr` may be set bogusly in some shells, making Poetry target the
  read-only system Python. Use the in-project `.venv` directly
  (`unset VIRTUAL_ENV && .venv/bin/python -m pytest ...`).
- `pipx upgrade <name>` / `pipx install <name>` from inside the repo treats
  `<name>` as a path if a matching subdir exists — run it from another directory
  (e.g. `$HOME` or `/tmp`). `brainpalace uninstall` handles this automatically
  by changing to `$HOME` before exec-ing pipx/uv.

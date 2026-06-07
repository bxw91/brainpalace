---
last_validated: 2026-06-07
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

1. **Land all work on `stable`** and get `task before-push` green
   (`export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` first, or
   Poetry dies on the headless keyring).
2. **Pick the version** — check `git tag` for the latest `vYY.M.N`; increment N
   within the month (resets monthly).
3. **Bump `version` in all three** `brainpalace-cli/pyproject.toml`,
   `brainpalace-server/pyproject.toml`, **and** `brainpalace-dashboard/pyproject.toml`
   — plus the dashboard's hardcoded `brainpalace_dashboard/__init__.py`
   `__version__` (the dashboard does **not** derive it from metadata). The cli +
   server derive `__version__`, so nothing else needs touching there. The
   `test_version_consistency.py` guard enforces all three pyprojects **and** the
   dashboard `__version__` moved together.
4. **Reinstall** so editable `--version` reflects the bump: `task install`.
5. **Changelog** — add the `[YY.M.N]` section in `docs/CHANGELOG.md`.
6. **Refresh doc freshness** — any audited doc whose content changed this
   release must be re-read against the code and have its `last_validated` date
   bumped. List stale docs with `python scripts/check_doc_freshness.py`; after
   re-reading, stamp them (`python scripts/add_audit_metadata.py` for today, or
   `--from-git` to backfill per-file content dates). The gate in step 8 enforces
   this — a doc committed after its `last_validated` fails the build. The rule's
   meaning lives in [DEVELOPERS_GUIDE.md](DEVELOPERS_GUIDE.md#documentation-freshness-last_validated).
7. **Dashboard parity** — confirm every new config option / CLI command /
   server endpoint this release is surfaced in the control-plane dashboard or
   allowlisted with a reason. Enforced by `task lint:dashboard-parity` (part of
   the step-8 gate); the rule lives in
   [DEVELOPERS_GUIDE.md](DEVELOPERS_GUIDE.md#dashboard-parity-surface-every-feature).
   - [ ] `task before-push` green (includes `lint:dashboard-parity`) — every new
         config/CLI/endpoint is surfaced in the dashboard or allowlisted.
8. **Gate**: `task before-push` must exit 0.
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
    If the publish step fails, fix the cause and ship a new patch `N+1` — a PyPI
    version can never be re-uploaded.
13. **Refresh the cli lock** so the committed lock and local cli-from-source
    builds pull the matching server: `(cd brainpalace-cli && poetry update
    brainpalace-rag --lock)`, then commit on `stable`. The cli depends on
    `brainpalace-rag` by PyPI version (not a local path), so `task install` for
    the cli installs whatever the lock pins — without this step a cli-from-source
    dev env keeps the *previous* server release. The pin stays `^YY.M.1`; only the
    lock entry moves. Run it **after** step 12 confirms the new version is live on
    PyPI. (Poetry caches the index — if the new version isn't picked up, clear it:
    `rm -rf ~/.cache/pypoetry/_http && poetry update brainpalace-rag --lock`.)

## Environment gotchas

- `VIRTUAL_ENV=/usr` may be set bogusly in some shells, making Poetry target the
  read-only system Python. Use the in-project `.venv` directly
  (`unset VIRTUAL_ENV && .venv/bin/python -m pytest ...`).
- `pipx upgrade <name>` / `pipx install <name>` from inside the repo treats
  `<name>` as a path if a matching subdir exists — run it from another directory
  (e.g. `$HOME` or `/tmp`). `brainpalace uninstall` handles this automatically
  by changing to `$HOME` before exec-ing pipx/uv.

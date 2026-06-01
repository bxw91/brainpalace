# Releasing BrainPalace

CalVer `YY.M.N` (2-digit year · month · Nth release that month). `brainpalace-cli`
and `brainpalace-rag` (server) **release in lockstep at the same version**.

## How publishing works — read this first

**PyPI publishing is automated.** The `.github/workflows/publish-to-pypi.yml`
workflow fires `on: release: published` and uploads both packages (server first,
then cli) using a **PyPI Trusted Publisher (OIDC)** — short-lived, repo-scoped,
**no API token**.

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
3. **Bump `version` in BOTH** `brainpalace-cli/pyproject.toml` **and**
   `brainpalace-server/pyproject.toml`. Nothing else needs the version
   (`__version__` is derived). The consistency test enforces both moved.
4. **Reinstall** so editable `--version` reflects the bump: `task install`.
5. **Changelog** — add the `[YY.M.N]` section in `docs/CHANGELOG.md`.
6. **Gate**: `task before-push` must exit 0.
7. **Commit on `stable`** (version bump + changelog).
8. **Mirror to `main`** (the squashed published branch — full `stable` history
   is never pushed) and tag:
   ```bash
   git checkout -B main brainpalace/main
   git read-tree --reset -u stable        # main tree := stable tree
   git commit -m "BrainPalace YY.M.N"     # single squashed commit
   git tag -a vYY.M.N -m "BrainPalace YY.M.N"
   git push brainpalace main && git push brainpalace vYY.M.N
   git checkout stable
   ```
9. **Create the GitHub Release — this publishes to PyPI:**
   ```bash
   gh release create vYY.M.N --repo bxw91/brainpalace \
     --title "BrainPalace YY.M.N" --notes-file <notes>
   ```
   The `publish-to-pypi.yml` workflow runs the quality gate, then publishes
   `brainpalace-rag` and `brainpalace-cli` via OIDC (it waits for the server to
   appear on PyPI before publishing the cli). **Do not publish manually.**
10. **Verify the run is green** and both versions are live:
    ```bash
    gh run list --repo bxw91/brainpalace --workflow publish-to-pypi.yml --limit 1
    curl -s https://pypi.org/pypi/brainpalace-rag/json | python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])'
    curl -s https://pypi.org/pypi/brainpalace-cli/json | python3 -c 'import sys,json;print(json.load(sys.stdin)["info"]["version"])'
    ```
    If the publish step fails, fix the cause and ship a new patch `N+1` — a PyPI
    version can never be re-uploaded.
11. **(Optional, dev parity)** Refresh the cli lock so local dev pulls the
    matching server: `(cd brainpalace-cli && poetry update brainpalace-rag --lock)`,
    then commit on `stable`. The pin stays `^YY.M.1`; only the lock entry moves.
    (Poetry caches the index — if the new version isn't picked up, clear it:
    `rm -rf ~/.cache/pypoetry/_http && poetry update brainpalace-rag --lock`.)

## Environment gotchas

- `VIRTUAL_ENV=/usr` may be set bogusly in some shells, making Poetry target the
  read-only system Python. Use the in-project `.venv` directly
  (`unset VIRTUAL_ENV && .venv/bin/python -m pytest ...`).
- `pipx upgrade <name>` / `pipx install <name>` from inside the repo treats
  `<name>` as a path if a matching subdir exists — run it from another directory
  (e.g. `$HOME` or `/tmp`).

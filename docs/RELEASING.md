# Releasing BrainPalace

CalVer `YY.M.N` (2-digit year · month · Nth release that month). `brainpalace-cli`
and `brainpalace-rag` (server) **release in lockstep at the same version**.

## Version: one source of truth

The version lives in **one place per package**: `pyproject.toml`.

- `brainpalace_cli/__init__.py` and `brainpalace_server/__init__.py` derive
  `__version__` from installed package metadata
  (`importlib.metadata.version(...)`) — **do not** hardcode a version string
  there. `__version__` feeds `--version` for both CLIs *and* the server's HTTP
  surface (`/health`, `/runtime`, OpenAPI).
- Because `__version__` reads metadata, **editable dev installs only reflect a
  new version after reinstall** (`task install`). Built wheels always carry the
  correct version straight from `pyproject.toml`, so published artifacts are
  never wrong — this is the guarantee that matters.
- `tests/test_version_consistency.py` (cli) fails the gate if the two
  `pyproject.toml` versions drift apart.

> History: 26.6.1 shipped with hardcoded `__version__ = "26.5.1"` left behind
> when only `pyproject.toml` was bumped — the wheels reported the wrong version
> over `--version` and HTTP. Metadata-derived `__version__` makes that
> impossible to repeat.

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
6. **Gate again**: `task before-push` must exit 0.
7. **Publish to PyPI — server first** (the cli depends on it):
   ```bash
   export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
   # token in ~/.config/pypoetry/auth.toml (NOT the OS keyring, which the
   # headless env can't read): poetry config pypi-token.pypi <token>
   (cd brainpalace-server && poetry build && poetry publish)
   # verify it is live, then:
   (cd brainpalace-cli && poetry build && poetry publish --skip-existing)
   ```
   PyPI uploads are **immutable** — a version can never be re-uploaded. A bad
   publish means shipping a new patch `N+1`, not overwriting.
8. **Refresh the cli lock** once the server wheel is on PyPI (so dev pulls the
   matching server): `(cd brainpalace-cli && poetry update brainpalace-rag --lock)`.
   The pin stays `^YY.M.1` (it already permits later same-year releases); only
   the lock entry moves. Commit on `stable`.
9. **Mirror to `main`** (the squashed published branch — full `stable` history
   is never pushed):
   ```bash
   git checkout -B main brainpalace/main
   git read-tree --reset -u stable        # main tree := stable tree
   git commit -m "BrainPalace YY.M.N"     # single squashed commit
   git tag -a vYY.M.N -m "BrainPalace YY.M.N"
   git push brainpalace main && git push brainpalace vYY.M.N
   git checkout stable
   ```
10. **GitHub release**: `gh release create vYY.M.N --repo bxw91/brainpalace
    --title "BrainPalace YY.M.N" --notes-file <notes>`.

## Environment gotchas

- `VIRTUAL_ENV=/usr` may be set bogusly in some shells, making Poetry target the
  read-only system Python. Use the in-project `.venv` directly
  (`unset VIRTUAL_ENV && .venv/bin/python -m pytest ...`).
- The PyPI token must live in `~/.config/pypoetry/auth.toml`
  (`PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring poetry config
  pypi-token.pypi <token>`); a token stored in the OS keyring is invisible to
  headless shells.
- `pipx upgrade <name>` from inside the repo treats `<name>` as a path if a
  matching subdir exists — run it from another directory (e.g. `$HOME`).

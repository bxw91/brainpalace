#!/usr/bin/env python3
"""Bump the BrainPalace lockstep version across every declaration site.

RELEASING.md step 3 lists six places the CalVer version is declared; they must
move together or ``brainpalace-cli/tests/test_version_consistency.py`` fails the
gate. This script is the single mechanical entry point so a release never
hand-edits five files and forgets the sixth.

Sites bumped (all to the same ``YY.M.N`` string):
  1. brainpalace-cli/pyproject.toml            (``version = "..."``)
  2. brainpalace-server/pyproject.toml         (``version = "..."``)
  3. brainpalace-dashboard/pyproject.toml      (``version = "..."``)
  4. brainpalace-dashboard/brainpalace_dashboard/__init__.py  (``__version__``)
  5. brainpalace-plugin/.claude-plugin/plugin.json            (``"version"``)
  6. .claude-plugin/marketplace.json           (``plugins[0].version`` only)

The marketplace catalog carries its OWN top-level ``version`` (a different
concept, e.g. ``2.0.0``) that must NOT change — so the marketplace edit matches
the *old package version string* rather than the ``version`` key, leaving the
catalog version alone. All edits are line-scoped regex substitutions so JSON/TOML
formatting is preserved byte-for-byte (no reformat noise in the release diff).

Usage:
    python scripts/bump_version.py 26.7.2
    python scripts/bump_version.py 26.7.2 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CALVER_RE = re.compile(r"^\d{2}\.\d{1,2}\.\d+$")

# (relative path, regex matching the whole declaration line, replacement template
#  taking the new version). count is always 1 — a second match means an
#  unexpected duplicate and we fail loudly rather than guess.
_PYPROJECTS = (
    "brainpalace-cli/pyproject.toml",
    "brainpalace-server/pyproject.toml",
    "brainpalace-dashboard/pyproject.toml",
)


def _current_version() -> str:
    text = (ROOT / "brainpalace-cli/pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', text, re.M)
    if not m:
        raise SystemExit(
            "bump_version: could not read current version from cli pyproject"
        )
    return m.group(1)


def _sub_line(rel: str, pattern: str, replacement: str, *, dry_run: bool) -> str:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if n != 1:
        raise SystemExit(
            f"bump_version: {rel}: expected exactly 1 match for {pattern!r}, got {n}"
        )
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return rel


def bump(new_version: str, *, dry_run: bool = False) -> list[str]:
    if not _CALVER_RE.match(new_version):
        raise SystemExit(
            f"bump_version: {new_version!r} is not CalVer YY.M.N (e.g. 26.7.2)"
        )
    old_version = _current_version()
    if old_version == new_version:
        # Idempotent: re-running `release:prep` after a gate fix must not fail.
        print(f"bump_version: already at {new_version} — nothing to bump")
        return []
    touched: list[str] = []

    for pp in _PYPROJECTS:
        touched.append(
            _sub_line(
                pp, r'^version = "[^"]+"', f'version = "{new_version}"', dry_run=dry_run
            )
        )
    touched.append(
        _sub_line(
            "brainpalace-dashboard/brainpalace_dashboard/__init__.py",
            r'^__version__ = "[^"]+"',
            f'__version__ = "{new_version}"',
            dry_run=dry_run,
        )
    )
    touched.append(
        _sub_line(
            "brainpalace-plugin/.claude-plugin/plugin.json",
            r'"version": "[^"]+"',
            f'"version": "{new_version}"',
            dry_run=dry_run,
        )
    )
    # Match the OLD package version specifically so the catalog's own top-level
    # version (a different value) is never touched.
    touched.append(
        _sub_line(
            ".claude-plugin/marketplace.json",
            rf'"version": "{re.escape(old_version)}"',
            f'"version": "{new_version}"',
            dry_run=dry_run,
        )
    )

    verb = "would bump" if dry_run else "bumped"
    print(f"{verb} {old_version} -> {new_version} across {len(touched)} sites:")
    for rel in touched:
        print(f"  {rel}")
    return touched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="new CalVer version, e.g. 26.7.2")
    parser.add_argument(
        "--dry-run", action="store_true", help="print what would change, write nothing"
    )
    args = parser.parse_args()
    bump(args.version, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

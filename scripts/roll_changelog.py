#!/usr/bin/env python3
"""Roll ``docs/CHANGELOG.md`` at release time.

RELEASING.md step 5: the accumulating ``## [Unreleased]`` section becomes
``## [YY.M.N] - DATE`` and a fresh empty ``## [Unreleased]`` (with its boilerplate
explainer) is left above it, so the next between-release commit has a bucket and
never hand-numbers an unreleased header.

The transform keeps the ``## [Unreleased]`` heading and its leading italic
explainer paragraph in place (they belong to the *new* empty section) and inserts
``## [YY.M.N] - DATE`` immediately before the first real entry heading
(``### Added`` / ``### Fixed`` / …). Fails loudly if there is nothing to release
(no entry headings under Unreleased) so a release can't ship an empty version.

Usage:
    python scripts/roll_changelog.py 26.7.2
    python scripts/roll_changelog.py 26.7.2 --date 2026-07-05 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "docs/CHANGELOG.md"

_UNRELEASED_RE = re.compile(r"^##\s*\[Unreleased\]\s*$", re.I)
_SECTION_RE = re.compile(r"^##\s*\[")  # any `## [...]` release heading
_ENTRY_RE = re.compile(r"^###\s+\S")  # `### Added` etc.


def roll(version: str, *, on: str, dry_run: bool = False) -> str:
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()

    # Find the Unreleased heading.
    unreleased_idx = next(
        (i for i, ln in enumerate(lines) if _UNRELEASED_RE.match(ln)), None
    )
    if unreleased_idx is None:
        raise SystemExit("roll_changelog: no `## [Unreleased]` heading found")

    # Idempotent: a second run (e.g. re-running `release:prep` after a gate fix)
    # must be a no-op, not an error — checked BEFORE the "no entries" guard, since
    # after a successful roll the fresh `## [Unreleased]` is legitimately empty.
    if any(re.match(rf"^##\s*\[{re.escape(version)}\]", ln) for ln in lines):
        print(f"roll_changelog: `## [{version}]` already present — nothing to roll")
        return CHANGELOG.read_text(encoding="utf-8")

    # Bound the Unreleased section at the next `## [` heading (previous release).
    end_idx = next(
        (
            i
            for i in range(unreleased_idx + 1, len(lines))
            if _SECTION_RE.match(lines[i])
        ),
        len(lines),
    )

    # First real entry heading inside the section = where the version header goes.
    entry_idx = next(
        (i for i in range(unreleased_idx + 1, end_idx) if _ENTRY_RE.match(lines[i])),
        None,
    )
    if entry_idx is None:
        raise SystemExit(
            "roll_changelog: `## [Unreleased]` has no entries — nothing to release"
        )

    header = f"## [{version}] - {on}"

    # Insert the version header (blank line, header, blank line) before the entries.
    new_lines = lines[:entry_idx] + [header, ""] + lines[entry_idx:]
    new_text = "\n".join(new_lines) + "\n"

    if dry_run:
        print(f"roll_changelog: would insert `{header}` before line {entry_idx + 1}")
    else:
        CHANGELOG.write_text(new_text, encoding="utf-8")
        print(
            f"roll_changelog: inserted `{header}`; fresh `## [Unreleased]` kept above"
        )
    return new_text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="new CalVer version, e.g. 26.7.2")
    parser.add_argument(
        "--date", default=date.today().isoformat(), help="release date (default: today)"
    )
    parser.add_argument("--dry-run", action="store_true", help="write nothing")
    args = parser.parse_args()
    try:
        date.fromisoformat(args.date)
    except ValueError:
        raise SystemExit(
            f"roll_changelog: invalid date {args.date!r} (want YYYY-MM-DD)"
        ) from None
    roll(args.version, on=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

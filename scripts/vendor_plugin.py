#!/usr/bin/env python3
"""Vendor the canonical Claude Code plugin into the CLI package for packaging.

The CLI's ``install-agent`` command converts the canonical plugin layout
(``brainpalace-plugin/``) into other runtimes (Codex, OpenCode, Gemini,
skill-runtime). For that to work on a standalone ``pipx install brainpalace``
— no repo checkout, no Claude Code marketplace on disk — the plugin must ship
*inside* the CLI wheel.

This copies ``brainpalace-plugin/`` → ``brainpalace-cli/brainpalace_cli/data/plugin/``
so ``[tool.poetry] include`` can force-package it. The vendored copy is
gitignored generated output (like the dashboard's built ``static/``), so it is
rebuilt at packaging time and never committed. ``task cli:build`` runs this
first; the release + before-push CI rehearsal build through the same task.

Idempotent: wipes and re-copies the destination each run.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "brainpalace-plugin"
DEST = REPO_ROOT / "brainpalace-cli" / "brainpalace_cli" / "data" / "plugin"

# Never vendor VCS / editor / build cruft.
_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", "node_modules", ".DS_Store"
)


def main() -> int:
    if not (SOURCE / "commands").is_dir():
        print(
            f"error: canonical plugin source not found at {SOURCE} "
            "(expected a 'commands/' directory)",
            file=sys.stderr,
        )
        return 1

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, DEST, ignore=_IGNORE)

    file_count = sum(1 for _ in DEST.rglob("*") if _.is_file())
    print(f"vendored plugin: {SOURCE} -> {DEST} ({file_count} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stamp audited docs: last_validated frontmatter + the freshness hash manifest.

Usage:
    python scripts/add_audit_metadata.py [--date YYYY-MM-DD] [--dry-run]

For every audited documentation file:
  - writes `last_validated: YYYY-MM-DD` into the YAML frontmatter (human-readable
    "confirmed on" date); files without frontmatter get a new block prepended,
  - records the hash of the file's authored portion in the sidecar manifest
    `scripts/doc_freshness.json` — the value the freshness gate
    (check_doc_freshness.py) actually compares against.

The hash lives in the manifest, NOT in each doc's frontmatter, so the docs render
clean on GitHub. Any legacy `validated_hash:` frontmatter line is stripped.
"""

import argparse
import glob
import os
import re
import sys
from datetime import date

# Project root: where this script lives is scripts/, so go up one level
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Same audited doc set as check_doc_links.py
DEFAULT_GLOBS = [
    "docs/*.md",
    "brainpalace-plugin/commands/*.md",
    "brainpalace-plugin/skills/*/references/*.md",
    "brainpalace-plugin/agents/*.md",
]

STANDALONE_FILES = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/CLAUDE.md",
]

# Frontmatter boundary pattern
FRONTMATTER_RE = re.compile(r"^---\s*\n", re.MULTILINE)


def resolve_files(root: str) -> list:
    """Resolve all audited doc files, excluding plans/ and design/."""
    files = set()
    for g in DEFAULT_GLOBS:
        pattern = os.path.join(root, g)
        for f in glob.glob(pattern, recursive=True):
            if os.path.isfile(f):
                files.add(os.path.abspath(f))
    for f in STANDALONE_FILES:
        full = os.path.join(root, f)
        if os.path.isfile(full):
            files.add(os.path.abspath(full))
    # Exclude out-of-scope directories
    files = {
        f
        for f in files
        if "/plans/" not in f and "/design/" not in f
    }
    return sorted(files)


def has_frontmatter(content: str) -> bool:
    """Check if content starts with YAML frontmatter (---\\n)."""
    return content.startswith("---\n") or content.startswith("---\r\n")


def update_frontmatter(content: str, audit_date: str) -> tuple:
    """Set last_validated in frontmatter and strip any legacy validated_hash line.

    Returns (new_content, action) where action is 'updated', 'added',
    'new_frontmatter', or 'current'.
    """
    block = f"---\nlast_validated: {audit_date}\n---\n\n{content}"
    if not has_frontmatter(content):
        # No frontmatter - prepend new block
        return block, "new_frontmatter"

    # Find the closing --- of frontmatter (first --- is at position 0).
    lines = content.split("\n")
    closing_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            closing_idx = i
            break

    if closing_idx is None:
        # Malformed frontmatter (no closing ---), treat as no frontmatter
        return block, "new_frontmatter"

    fm_lines = lines[1:closing_idx]
    # Drop any legacy validated_hash line (hashes now live in the manifest).
    fm_lines = [ln for ln in fm_lines if not ln.startswith("validated_hash:")]

    found = False
    for j, line in enumerate(fm_lines):
        if line.startswith("last_validated:"):
            fm_lines[j] = f"last_validated: {audit_date}"
            found = True
            break
    if not found:
        fm_lines.append(f"last_validated: {audit_date}")

    new_lines = ["---"] + fm_lines + lines[closing_idx:]
    new_content = "\n".join(new_lines)
    if new_content == content:
        return content, "current"
    return new_content, "updated" if found else "added"


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Add last_validated frontmatter to audited docs"
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Audit date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--from-git",
        action="store_true",
        help=(
            "Stamp each file with its own last content-change date from git "
            "(ignores frontmatter-only commits) instead of a single --date. "
            "Use to backfill truthful per-file dates."
        ),
    )
    parser.add_argument(
        "--keep-date",
        action="store_true",
        help=(
            "Preserve each file's existing last_validated; only (re)stamp "
            "validated_hash. Files with no existing date fall back to --date. "
            "Use to backfill validated_hash without re-claiming validation."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing files",
    )
    args = parser.parse_args()

    # Validate date format
    try:
        date.fromisoformat(args.date)
    except ValueError:
        print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)

    # Reuse the freshness checker's authored-content hash + manifest so the stamp
    # matches exactly what the gate recomputes.
    from check_doc_freshness import (
        content_hash,
        last_validated,
        load_manifest,
        save_manifest,
    )

    per_file_date = None
    if args.from_git:
        # Reuse the freshness checker's content-change-date logic.
        from check_doc_freshness import last_content_commit_date
        per_file_date = last_content_commit_date

    audit_date = args.date
    files = resolve_files(PROJECT_ROOT)
    old_manifest = load_manifest()
    new_manifest = {}  # rebuilt from the resolved set (prunes orphan entries)

    updated = 0
    added = 0
    new_fm = 0
    current = 0
    errors = 0

    for filepath in files:
        rel = os.path.relpath(filepath, PROJECT_ROOT)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, IOError) as e:
            print(f"  ERROR reading {rel}: {e}", file=sys.stderr)
            errors += 1
            continue

        file_date = audit_date
        if args.keep_date:
            existing = last_validated(content)
            if existing:
                file_date = existing
        if per_file_date is not None:
            gd = per_file_date(filepath)
            if not gd:
                # Untracked file — nothing committed to date from; skip.
                if args.dry_run:
                    print(f"  SKIP (untracked): {rel}")
                continue
            file_date = gd

        new_content, action = update_frontmatter(content, file_date)
        digest = content_hash(new_content)
        new_manifest[rel] = digest
        manifest_changed = old_manifest.get(rel) != digest

        if action == "current" and not manifest_changed:
            current += 1
            if args.dry_run:
                print(f"  SKIP (current): {rel}")
            continue

        if action == "current":
            label = "HASH"  # frontmatter unchanged, manifest hash (re)stamped
            updated += 1
        elif action == "updated":
            updated += 1
            label = "UPDATE"
        elif action == "added":
            added += 1
            label = "ADD FIELD"
        else:  # new_frontmatter
            new_fm += 1
            label = "NEW FRONTMATTER"

        if args.dry_run:
            print(f"  {label}: {rel}")
        else:
            if new_content != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
            print(f"  {label}: {rel}")

    manifest_dirty = new_manifest != old_manifest
    if not args.dry_run:
        save_manifest(new_manifest)
    elif manifest_dirty:
        print("  (manifest scripts/doc_freshness.json would be rewritten)")

    # Summary
    total = updated + added + new_fm
    mode = " (dry-run)" if args.dry_run else ""
    print(f"\nSummary{mode}:")
    print(f"  Files processed: {len(files)}")
    print(f"  Frontmatter/last_validated updates: {updated}")
    print(f"  Added last_validated to frontmatter: {added}")
    print(f"  Added new frontmatter block: {new_fm}")
    print(f"  Already current: {current}")
    print(f"  Total modified: {total}")
    print(f"  Manifest entries: {len(new_manifest)}")
    if errors:
        print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()

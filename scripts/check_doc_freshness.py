#!/usr/bin/env python3
"""Fail when an audited doc was changed after its last_validated date.

Usage:
    python scripts/check_doc_freshness.py [--json] [glob1 glob2 ...]

For every audited documentation file, compares the file's last git commit
date against the `last_validated:` value in its YAML frontmatter. A file is
STALE when:
  - it has no `last_validated` field, or
  - its last commit date is newer than `last_validated`.

Exit code is non-zero if any file is stale, so this can gate `before-push`.
After re-reading a stale doc against the code, run
`scripts/add_audit_metadata.py` to stamp today's date and clear it.

Uncommitted working-tree changes are ignored — freshness is measured against
committed history, matching what reviewers and CI see.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

# Project root: where this script lives is scripts/, so go up one level
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Same audited doc set as add_audit_metadata.py / check_doc_links.py
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

LAST_VALIDATED_RE = re.compile(r"^last_validated:\s*(.+?)\s*$", re.MULTILINE)


def resolve_files(root: str, globs: list) -> list:
    """Resolve audited doc files, excluding plans/ and design/."""
    files = set()
    for g in globs:
        for f in glob.glob(os.path.join(root, g), recursive=True):
            if os.path.isfile(f):
                files.add(os.path.abspath(f))
    for f in STANDALONE_FILES:
        full = os.path.join(root, f)
        if os.path.isfile(full):
            files.add(os.path.abspath(full))
    files = {f for f in files if "/plans/" not in f and "/design/" not in f}
    return sorted(files)


def read_frontmatter(content: str) -> str:
    """Return the YAML frontmatter block, or '' if none."""
    if not (content.startswith("---\n") or content.startswith("---\r\n")):
        return ""
    lines = content.split("\n")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i])
    return ""


def last_validated(content: str):
    """Extract last_validated date string from frontmatter, or None."""
    fm = read_frontmatter(content)
    if not fm:
        return None
    m = LAST_VALIDATED_RE.search(fm)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def _commit_touches_content(sha: str, filepath: str) -> bool:
    """True if commit `sha` changed body content in `filepath`, not just frontmatter.

    Frontmatter-only changes are treated as metadata, not content — so neither
    re-stamping a doc's `last_validated:` line nor the commit that first
    *introduces* the frontmatter block (`---` fences + keys) makes the doc look
    freshly edited on the next freshness run.
    """
    try:
        out = subprocess.run(
            ["git", "show", sha, "--format=", "--unified=0", "--", filepath],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return True  # can't tell — assume content changed, stay conservative
    for line in out.stdout.splitlines():
        if not (line.startswith("+") or line.startswith("-")):
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue  # diff file headers
        body = line[1:].strip()
        # Frontmatter-block lines are metadata: the `---` fences, blank lines,
        # and the `last_validated:` key. Anything else is real body content.
        if body == "" or body == "---" or body.startswith("last_validated:"):
            continue
        return True  # a non-metadata line was added/removed
    return False


def last_content_commit_date(filepath: str) -> str:
    """Date (YYYY-MM-DD) of the newest commit that changed real content.

    Walks the file's history newest-first and returns the first commit whose
    diff touches something other than the `last_validated` line. Returns '' if
    the file is untracked. Falls back to the oldest commit date if every commit
    is metadata-only (e.g. a doc created with only frontmatter).
    """
    try:
        out = subprocess.run(
            ["git", "log", "--format=%H %cs", "--", filepath],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    rows = [ln.split(" ", 1) for ln in out.stdout.splitlines() if ln.strip()]
    if not rows:
        return ""
    for sha, cdate in rows:
        if _commit_touches_content(sha, filepath):
            return cdate.strip()
    return rows[-1][1].strip()  # all metadata-only — use first-ever commit


# Backwards-compatible alias.
git_commit_date = last_content_commit_date


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fail when audited docs are stale vs last_validated"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("globs", nargs="*", help="Override default doc globs")
    args = parser.parse_args()

    globs = args.globs or DEFAULT_GLOBS
    files = resolve_files(PROJECT_ROOT, globs)

    stale = []  # (rel, reason, commit_date, validated)
    checked = 0

    for filepath in files:
        rel = os.path.relpath(filepath, PROJECT_ROOT)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, IOError):
            continue

        validated = last_validated(content)
        commit = last_content_commit_date(filepath)
        if not commit:
            # Untracked / never committed — skip, nothing to compare against.
            continue
        checked += 1

        if validated is None:
            stale.append((rel, "missing last_validated", commit, "-"))
        elif commit > validated:
            stale.append((rel, "edited after validation", commit, validated))

    if args.json:
        print(json.dumps(
            {
                "checked": checked,
                "stale_count": len(stale),
                "stale": [
                    {"file": r, "reason": why, "commit": c, "last_validated": v}
                    for (r, why, c, v) in stale
                ],
            },
            indent=2,
        ))
    else:
        if stale:
            print(f"Stale docs ({len(stale)}/{checked}) — last_validated is behind git history:\n")
            for rel, why, commit, validated in stale:
                print(f"  {rel}")
                print(f"    {why} (last content change {commit}, last_validated {validated})")
            print(
                "\nFix: re-check each doc against the code, then run "
                "`python scripts/add_audit_metadata.py` to stamp today's date."
            )
        else:
            print(f"All {checked} audited docs fresh (last_validated >= last commit date).")

    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()

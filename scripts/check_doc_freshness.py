#!/usr/bin/env python3
"""Fail when an audited doc's authored content changed since it was validated.

Usage:
    python scripts/check_doc_freshness.py [--json] [glob1 glob2 ...]

For every audited documentation file, compares a hash of the file's authored
content (the `human_portion` — prose + non-contract frontmatter, with
machine-owned GENERATED blocks and metadata stripped) against the hash recorded
for that file in the sidecar manifest `scripts/doc_freshness.json`. A file is
STALE when:
  - it has no entry in the manifest, or
  - the recomputed hash differs from the recorded one.

The hash compares *what the content is*, not *when it changed*, so an edit made
the same calendar day as validation is still caught — unlike a date comparison,
which is blind below day granularity. Hashes live in the manifest (not in each
doc's frontmatter) so the docs render clean on GitHub; `last_validated:` stays in
frontmatter as a human-readable "confirmed on" date but no longer gates.

Exit code is non-zero if any file is stale, so this can gate `before-push`.
After re-reading a stale doc against the code, run
`scripts/add_audit_metadata.py` to re-stamp `last_validated` + the manifest hash.

Working-tree content is hashed directly — no git history walk is needed for the
gate. (The git content-date helper below is retained for
`add_audit_metadata.py --from-git` backfill.)
"""

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

# Project root: where this script lives is scripts/, so go up one level
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Same audited doc set as add_audit_metadata.py / check_doc_links.py. Skill
# SKILL.md files are GLOBBED so a brand-new skill is registered automatically by
# `add_audit_metadata.py` — no manual edit. The one generated, ai-guidance-gated
# SKILL.md is removed by FRESHNESS_EXEMPT below (it must not be double-gated).
DEFAULT_GLOBS = [
    "docs/*.md",
    "brainpalace-plugin/commands/*.md",
    "brainpalace-plugin/skills/*/SKILL.md",
    "brainpalace-plugin/skills/*/references/*.md",
    "brainpalace-plugin/agents/*.md",
]

STANDALONE_FILES = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/CLAUDE.md",
    # Plugin README is a single fixed file (not glob-varying); register it here.
    "brainpalace-plugin/README.md",
]

# SKILL.md files owned by ANOTHER gate and excluded from freshness (repo-relative).
# Single-sourced from the doc-sync allowlist; fall back to the known path when
# brainpalace_cli isn't importable in an ad-hoc run.
try:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "brainpalace-cli"))
    from brainpalace_cli.doc_sync.allowlist import PLUGIN_DOC_GATE_EXEMPT

    FRESHNESS_EXEMPT = set(PLUGIN_DOC_GATE_EXEMPT)
except Exception:  # noqa: BLE001 — best-effort import; fall back to the known path
    FRESHNESS_EXEMPT = {"brainpalace-plugin/skills/using-brainpalace/SKILL.md"}

#: Sidecar manifest of authored-content hashes (kept out of doc frontmatter so
#: docs render clean on GitHub). Maps repo-relative path -> sha256 hex.
MANIFEST_PATH = os.path.join(PROJECT_ROOT, "scripts", "doc_freshness.json")

LAST_VALIDATED_RE = re.compile(r"^last_validated:\s*(.+?)\s*$", re.MULTILINE)


def load_manifest() -> dict:
    """Load the path->hash manifest, or {} if absent/unreadable."""
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, IOError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_manifest(manifest: dict) -> None:
    """Write the manifest sorted by key with a trailing newline (stable diffs)."""
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(manifest.items())), f, indent=2)
        f.write("\n")


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
    files = {
        f
        for f in files
        if os.path.relpath(f, root).replace(os.sep, "/") not in FRESHNESS_EXEMPT
    }
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


# --- human-owned portion (resolution 11/G) -------------------------------- #
# Machine-owned regions are excluded from freshness so a pure doc-sync regen
# (contract frontmatter keys + GENERATED blocks) never trips last_validated.

# Top-level frontmatter keys owned by the interface doc-sync generator.
CONTRACT_FRONTMATTER_KEYS = ("parameters",)
# Strip a GENERATED block AND an optional machine-emitted heading line directly
# above its open marker (the doc-sync generator emits `### Flags\n<!--GENERATED:
# flags-->`). The heading is constant machine-owned text, so it must not read as a
# human edit — otherwise creating a flags block trips last_validated freshness.
GENERATED_BLOCK_RE = re.compile(
    r"(?:^[ \t]*#{1,6}[ \t][^\n]*\n)?[ \t]*<!--GENERATED:[^>]*-->.*?<!--/GENERATED-->",
    re.DOTALL | re.MULTILINE,
)
_WHITESPACE_RE = re.compile(r"\s+")


def _split_doc(content: str):
    """Return (frontmatter, body). Frontmatter is '' when absent."""
    fm = read_frontmatter(content)
    if not fm:
        return "", content
    # Body is everything after the closing fence of the frontmatter block.
    lines = content.split("\n")
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return fm, "\n".join(lines[i + 1:])
    return fm, ""


def _strip_contract_frontmatter(fm: str) -> str:
    """Drop last_validated + machine-owned contract blocks (e.g. parameters:)."""
    out = []
    skip_block = False
    for line in fm.split("\n"):
        is_top_key = bool(line) and not line[0].isspace() and ":" in line
        if is_top_key:
            key = line.split(":", 1)[0].strip()
            if key in ("last_validated", "validated_hash"):
                continue
            skip_block = key in CONTRACT_FRONTMATTER_KEYS
            if skip_block:
                continue
        elif skip_block:
            continue  # indented line under a contract block
        out.append(line)
    return "\n".join(out)


def human_portion(content: str) -> str:
    """The human-owned slice used for freshness: prose + non-contract frontmatter,
    with machine-owned regions (contract frontmatter keys, GENERATED blocks) and
    whitespace removed. Two docs that differ only in machine-owned regions yield
    the same human portion, so regeneration does not look like a content edit."""
    fm, body = _split_doc(content)
    body = GENERATED_BLOCK_RE.sub("", body)
    combined = _strip_contract_frontmatter(fm) + "\n" + body
    return _WHITESPACE_RE.sub(" ", combined).strip()


def content_hash(content: str) -> str:
    """Stable hash of the authored portion, used as the freshness gate.

    Strips `validated_hash` itself (via human_portion) so stamping the hash does
    not change the thing being hashed — the value is self-consistent."""
    return hashlib.sha256(human_portion(content).encode("utf-8")).hexdigest()


def _file_at(sha: str, filepath: str):
    """Return the file's full text at commit `sha`, or None if absent there."""
    rel = os.path.relpath(filepath, PROJECT_ROOT)
    try:
        out = subprocess.run(
            ["git", "show", f"{sha}:{rel}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return out.stdout


def _commit_touches_content(sha: str, filepath: str) -> bool:
    """True if commit `sha` changed the HUMAN-owned portion of `filepath`.

    Compares the human portion (prose + non-contract frontmatter, machine-owned
    regions stripped) at the commit against its parent. So re-stamping
    `last_validated:`, introducing the frontmatter block, AND a pure doc-sync
    regeneration (contract `parameters:` / GENERATED blocks) all read as metadata
    — only a real prose/human-frontmatter edit counts as content.
    """
    current = _file_at(sha, filepath)
    if current is None:
        return True  # can't read — stay conservative
    parent = _file_at(f"{sha}^", filepath)
    parent_human = human_portion(parent) if parent is not None else ""
    return human_portion(current) != parent_human


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
        description="Fail when audited docs' authored content changed since validation"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("globs", nargs="*", help="Override default doc globs")
    args = parser.parse_args()

    globs = args.globs or DEFAULT_GLOBS
    files = resolve_files(PROJECT_ROOT, globs)
    manifest = load_manifest()

    stale = []  # (rel, reason, validated_date)
    checked = 0

    for filepath in files:
        rel = os.path.relpath(filepath, PROJECT_ROOT)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, IOError):
            continue
        checked += 1

        recorded = manifest.get(rel)
        validated = last_validated(content) or "-"

        if recorded is None:
            stale.append((rel, "missing from manifest", validated))
        elif recorded != content_hash(content):
            stale.append((rel, "content changed since validation", validated))

    if args.json:
        print(json.dumps(
            {
                "checked": checked,
                "stale_count": len(stale),
                "stale": [
                    {"file": r, "reason": why, "last_validated": v}
                    for (r, why, v) in stale
                ],
            },
            indent=2,
        ))
    else:
        if stale:
            print(f"Stale docs ({len(stale)}/{checked}) — authored content changed since validation:\n")
            for rel, why, validated in stale:
                print(f"  {rel}")
                print(f"    {why} (last_validated {validated})")
            print(
                "\nFix: re-check each doc against the code, then run "
                "`python scripts/add_audit_metadata.py` to re-stamp "
                "last_validated + the manifest hash."
            )
        else:
            print(f"All {checked} audited docs fresh (manifest hash matches authored content).")

    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()

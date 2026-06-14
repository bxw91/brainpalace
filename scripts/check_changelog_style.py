#!/usr/bin/env python3
"""Fail when a changelog entry exceeds the style caps.

Usage:
    python scripts/check_changelog_style.py [--json] [path/to/CHANGELOG.md]

The changelog style rule (docs/DEVELOPERS_GUIDE.md → "Changelog style") caps
every entry at **3 sentences**: a bold lead naming what changed, one sentence
of user-facing impact, and at most one clause for the key default/gotcha.
Root-cause / file-level detail belongs in the commit message, not here.

A second cap guards against run-ons that dodge the sentence count by joining
clauses with ``;``/``—``: an entry may be at most **320 characters** (joined,
machine-neutral length). The sentence count is wrap-independent and so is this.

Scope:
  - The **3-sentence cap** lints the **[Unreleased]** section *and* the **most
    recent released** section (the two topmost, actively-edited sections).
  - The **320-char cap** lints the **[Unreleased]** section only — it is enforced
    at authoring time (entries land in [Unreleased] first) and does not fail
    already-versioned sections retroactively.
Older released sections predate the rules and are left alone (normalize them in
a deliberate pass, never fail the build retroactively).

Sentence counting is a heuristic tuned for the changelog's controlled style:
inline code spans and markdown link targets are stripped, CalVer dots
(``26.6.34``) and ellipses are neutralised, and common abbreviations are
protected — so only real sentence terminators are counted. Exit code is
non-zero if any in-scope entry exceeds the cap, so this gates ``before-push``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CHANGELOG = os.path.join(PROJECT_ROOT, "docs", "CHANGELOG.md")

MAX_SENTENCES = 3
#: Max characters per entry (joined). Guards run-ons that dodge the sentence cap
#: with ``;``/``—``. Enforced on the [Unreleased] section only — see module docs.
MAX_CHARS = 320

#: A version section heading like ``## [26.6.34] - 2026-06-11``.
_VERSION_HEADING = re.compile(r"^##\s+\[\d+\.\d+\.\d+\]")
#: The unreleased section heading.
_UNRELEASED_HEADING = re.compile(r"^##\s+\[Unreleased\]", re.IGNORECASE)
#: Any ``## [...]`` section heading.
_ANY_SECTION = re.compile(r"^##\s+\[")

_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "cf.", "Dr.", "Mr.", "Ms.")


def count_sentences(entry: str) -> int:
    """Heuristic sentence count for a single changelog entry's text."""
    text = entry
    # Strip inline code spans (`...`) — their punctuation is not prose.
    text = re.sub(r"`[^`]*`", " ", text)
    # Strip markdown link *targets* but keep the visible text: [text](url) -> text.
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Drop emphasis markers so a bold lead "**title.**" terminator is visible.
    text = text.replace("**", "").replace("*", "").replace("_", "")
    # Neutralise abbreviations whose dot is not a sentence end.
    for abbr in _ABBREVIATIONS:
        text = text.replace(abbr, abbr.replace(".", ""))
    # Collapse ellipses so they count as nothing.
    text = text.replace("...", " ").replace("…", " ")
    # Remove dots inside numbers (CalVer 26.6.34, decimals 0.5).
    text = re.sub(r"(?<=\d)\.(?=\d)", "", text)
    # A sentence terminator is . ! or ? immediately followed by whitespace or EOL.
    terminators = re.findall(r"[.!?]+(?=\s|$)", text)
    return len(terminators)


def _iter_entries(lines: list[str]):
    """Yield ``(line_no, heading, entry_text)`` for in-scope entries.

    In scope = the ``[Unreleased]`` section plus the first version section
    encountered (the most recent release). Entries are top-level ``- `` bullets;
    physical continuation lines are joined.
    """
    heading = None
    seen_version_section = False
    lint_active = False
    buf: list[str] = []
    buf_line = 0

    def flush():
        nonlocal buf, buf_line
        if buf:
            yield_val = (buf_line, heading, " ".join(b.strip() for b in buf))
            buf = []
            return yield_val
        return None

    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if _ANY_SECTION.match(line):
            # Close any open entry before switching sections.
            done = flush()
            if done:
                yield done
            is_unreleased = bool(_UNRELEASED_HEADING.match(line))
            is_version = bool(_VERSION_HEADING.match(line))
            if is_version:
                if seen_version_section:
                    # Past the most-recent release → stop linting entirely.
                    lint_active = False
                    heading = None
                    return
                seen_version_section = True
            heading = line.lstrip("# ").strip()
            lint_active = is_unreleased or is_version
            continue
        if not lint_active:
            continue
        if line.lstrip().startswith("- "):
            done = flush()
            if done:
                yield done
            buf = [line.lstrip()[2:]]
            buf_line = i
        elif line.strip() == "" or line.startswith("#") or line.startswith("  - "):
            # Blank line, sub-heading, or nested bullet ends the current entry.
            done = flush()
            if done:
                yield done
        elif buf:
            # Wrapped continuation of the current entry.
            buf.append(line)
    done = flush()
    if done:
        yield done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=DEFAULT_CHANGELOG)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with open(args.path, encoding="utf-8") as fh:
        lines = fh.readlines()

    violations = []
    for line_no, heading, entry in _iter_entries(lines):
        n = count_sentences(entry)
        if n > MAX_SENTENCES:
            violations.append(
                {
                    "line": line_no,
                    "section": heading,
                    "kind": "sentences",
                    "measure": n,
                    "limit": MAX_SENTENCES,
                    "entry": entry[:80],
                }
            )
        # The char cap is authoring-time only: [Unreleased] entries.
        is_unreleased = bool(heading and _UNRELEASED_HEADING.match(f"## {heading}"))
        if is_unreleased and len(entry) > MAX_CHARS:
            violations.append(
                {
                    "line": line_no,
                    "section": heading,
                    "kind": "chars",
                    "measure": len(entry),
                    "limit": MAX_CHARS,
                    "entry": entry[:80],
                }
            )

    rel = os.path.relpath(args.path, PROJECT_ROOT)
    if args.json:
        print(json.dumps({"violations": violations}, indent=2))
    else:
        if not violations:
            print(
                f"✓ {rel}: all in-scope entries are ≤ {MAX_SENTENCES} sentences "
                f"(and [Unreleased] entries ≤ {MAX_CHARS} chars)."
            )
        else:
            print(
                f"✗ {rel}: {len(violations)} entr"
                f"{'y' if len(violations) == 1 else 'ies'} exceed the style caps:\n"
            )
            for v in violations:
                unit = "sentences" if v["kind"] == "sentences" else "chars"
                print(
                    f"  {rel}:{v['line']} {v['section']} — "
                    f"{v['measure']} {unit} (cap {v['limit']}): \"{v['entry']}…\""
                )
            print(
                "\nTighten to: bold lead + one impact sentence + one gotcha "
                "clause. Push root-cause / file detail into the commit message.\n"
                "Rule: docs/DEVELOPERS_GUIDE.md → Changelog style."
            )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())

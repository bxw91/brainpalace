"""Skills surface: validate the `skills:` frontmatter field in command docs against
the live skill dirs, plus a referential check scoped to the `*-brainpalace` skill
naming convention (avoids false-positiving 'this skill')."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.referential import dangling_tokens

SURFACE = "skills"
# Skill-name convention in this repo: '<word>-brainpalace'. Scope the prose scan to it.
# Left boundary (?<![A-Za-z0-9]) stops substring matches like "Using-brainpalace"
# leaking "sing-brainpalace"; the suffix anchor keeps plain "this skill" prose out.
_SKILL_REF_RE = re.compile(r"`?(?<![A-Za-z0-9])([a-z][a-z0-9]*-brainpalace)`?")


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter; return {} when absent OR malformed.

    Unlike cli_commands._parse_frontmatter (which raises so the command surface can
    emit DriftKind.INVALID), skills frontmatter is optional — a missing or broken
    block is treated as 'no skills declared' rather than crashing run_check.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    try:
        _, fm, _ = text.split("---", 2)
        return yaml.safe_load(fm) or {}
    except (ValueError, yaml.YAMLError):
        return {}


class SkillsChecker:
    surface = SURFACE

    def __init__(
        self,
        skills_dir: Path,
        docs_dir: Path,
        extra_skills_dirs: Iterable[Path] = (),
    ) -> None:
        self.skills_dir = Path(skills_dir)
        self.docs_dir = Path(docs_dir)
        # Dev-only skills live in the repo's project scope (`.claude/skills`), not
        # the shipped plugin — e.g. `authoring-brainpalace-docs`. They must still
        # count as "live" so prose/`skills:` refs to them don't false-positive.
        self.extra_skills_dirs = tuple(Path(d) for d in extra_skills_dirs)

    def _live_skills(self) -> set[str]:
        out: set[str] = set()
        for base in (self.skills_dir, *self.extra_skills_dirs):
            for skill_md in base.glob("*/SKILL.md"):
                fm = _read_frontmatter(skill_md)
                out.add(str(fm.get("name") or skill_md.parent.name))
        return out

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        live = self._live_skills()
        records: list[DriftRecord] = []
        docs = sorted(self.docs_dir.glob("brainpalace-*.md"))
        for doc in docs:
            fm = _read_frontmatter(doc)
            for s in fm.get("skills") or []:
                if str(s) not in live:
                    records.append(
                        DriftRecord(
                            SURFACE,
                            str(s),
                            str(doc),
                            DriftKind.EXTRA,
                            f"`skills:` lists '{s}' which is not a live skill",
                        )
                    )
        records.extend(
            dangling_tokens(
                docs,
                _SKILL_REF_RE,
                live,
                SURFACE,
                "prose references unknown skill '{tok}'",
            )
        )
        return records

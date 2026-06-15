"""Plugin-docs surface: gate the WIDER plugin doc set against live code — agents,
the hand-authored `configuring-brainpalace` SKILL.md, skill references, and the
plugin README. The CLI-commands checker only covers `commands/`; these files
re-use the same command/skill names in prose and drift the same way.

Folder-SCANNED, never a hardcoded file list, so a new agent/skill/reference is
covered automatically. Two deterministic checks (no LLM, reusing the
command/skill machinery):

  * **referential drift** — a `brainpalace <cmd>` invocation or `<x>-brainpalace`
    skill reference naming something not live (catches renames/removals
    propagating into agent/reference prose; this is how the dead
    `brainpalace test-embedding`/`test-summarize` examples were found).
  * **fail-closed registry** — every scanned doc must be REGISTERED (carry a
    freshness-manifest entry, i.e. be stamped + freshness-gated) or be EXEMPT (an
    explicit allowlist entry naming the gate that already covers it). A brand-new
    agent/skill dropped into the folders FAILS until stamped, so new files can
    never enter ungated.

The generated `using-brainpalace/SKILL.md` is EXEMPT (see allowlist): it is
emitted from `ai_guidance.md` and gated by `lint:ai-guidance-parity`; gating it
here too would double-own the file.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from brainpalace_cli.doc_sync.allowlist import PLUGIN_DOC_GATE_EXEMPT
from brainpalace_cli.doc_sync.checkers.cli_commands import referential_drift
from brainpalace_cli.doc_sync.checkers.skills import _SKILL_REF_RE, _read_frontmatter
from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.referential import dangling_tokens

SURFACE = "plugin-docs"


class PluginDocsChecker:
    surface = SURFACE

    def __init__(
        self,
        plugin_dir: Path,
        repo_root: Path,
        registered: Iterable[str],
        skills_dir: Path | None = None,
        extra_skills_dirs: Iterable[Path] = (),
    ) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.repo_root = Path(repo_root)
        # Repo-relative paths already carried by the freshness manifest. A scanned
        # doc not present here (and not exempt) is an unregistered new file.
        self.registered = set(registered)
        self.skills_dir = Path(skills_dir) if skills_dir else self.plugin_dir / "skills"
        # Dev-only skills (e.g. .claude/skills/authoring-brainpalace-docs) must
        # count as live so prose refs to them don't false-positive — same rule the
        # SkillsChecker applies for command docs.
        self.extra_skills_dirs = tuple(Path(d) for d in extra_skills_dirs)

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.repo_root).as_posix()

    def _scanned_docs(self) -> list[Path]:
        """Every gated plugin doc, minus the explicit exemptions. Globs cover any
        future agent/skill/reference without touching this list."""
        pd = self.plugin_dir
        candidates: list[Path] = [
            *pd.glob("agents/*.md"),
            *pd.glob("skills/*/SKILL.md"),
            *pd.glob("skills/*/references/*.md"),
        ]
        readme = pd / "README.md"
        if readme.is_file():
            candidates.append(readme)
        return sorted(
            p for p in candidates if self._rel(p) not in PLUGIN_DOC_GATE_EXEMPT
        )

    def _live_skills(self) -> set[str]:
        out: set[str] = set()
        for base in (self.skills_dir, *self.extra_skills_dirs):
            if not base.is_dir():
                continue
            for skill_md in base.glob("*/SKILL.md"):
                fm = _read_frontmatter(skill_md)
                out.add(str(fm.get("name") or skill_md.parent.name))
        return out

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        docs = self._scanned_docs()
        records: list[DriftRecord] = []

        # 1) Fail-closed registry: unregistered new doc must be stamped or exempted.
        for doc in docs:
            rel = self._rel(doc)
            if rel not in self.registered:
                records.append(
                    DriftRecord(
                        SURFACE,
                        rel,
                        str(doc),
                        DriftKind.MISSING,
                        "plugin doc is not registered — stamp it "
                        "(`python scripts/add_audit_metadata.py`) so it is "
                        "freshness-gated, or add it to PLUGIN_DOC_GATE_EXEMPT "
                        "with a reason",
                    )
                )

        # 2) Referential drift: dangling command + skill references in prose.
        records.extend(referential_drift(docs, {c.name for c in snap.commands}))
        records.extend(
            dangling_tokens(
                docs,
                _SKILL_REF_RE,
                self._live_skills(),
                SURFACE,
                "prose references unknown skill '{tok}'",
            )
        )
        return records

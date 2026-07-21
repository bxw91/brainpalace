"""Base converter for skill+instruction-file runtimes.

Shared logic for runtimes that flatten the plugin into skill directories
(delegated to `SkillRuntimeConverter`) and additionally generate an
"instruction file" (AGENTS.md, QWEN.md, ...) at the project root, updated
idempotently via HTML comment markers.

Per-runtime variance is limited to three class attributes on the subclass:
    runtime_type: RuntimeType
    instruction_filename: str  (e.g. "AGENTS.md", "QWEN.md")
    header_label: str          (e.g. "Codex", "Qwen")

Everything else — skill-dir writes, header insertion, idempotent marker
replace, project-root derivation — is identical across runtimes and lives
here once.
"""

import logging
from pathlib import Path

from brainpalace_cli.runtime.skill_runtime_converter import (
    SkillRuntimeConverter,
    _skill_dir_name,
)
from brainpalace_cli.runtime.types import (
    PluginAgent,
    PluginBundle,
    PluginCommand,
    PluginSkill,
    RuntimeType,
    Scope,
)

logger = logging.getLogger(__name__)

# HTML comment markers for idempotent instruction-file updates
INSTRUCTION_FILE_START = "<!-- brainpalace:start -->"
INSTRUCTION_FILE_END = "<!-- brainpalace:end -->"

INSTRUCTION_FILE_SECTION = """\
{start_marker}

## BrainPalace

BrainPalace provides semantic search over your codebase and documentation.

### Available Skills

| Skill | Description |
|-------|-------------|
{skill_table}

### Usage

Ask your AI assistant to search documentation or code:

- "Search for authentication patterns in my codebase"
- "Find documentation about the API endpoints"
- "Look up how error handling works"

### Setup

Run `brainpalace start` to start the BrainPalace server, then use
`brainpalace index ./src` to index your source code.

{end_marker}"""


def add_instruction_header(content: str, name: str, label: str) -> str:
    """Add an invocation guidance header after the frontmatter.

    Inserts a brief note about how to invoke this skill in the target
    runtime (identified by `label`, e.g. "Codex", "Qwen").
    """
    # Split on the closing --- of frontmatter
    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return content

    header = (
        f"> **{label} Skill:** `{name}`\n"
        f"> Invoke by asking about {name} or referencing it directly.\n\n"
    )
    return f"---\n{parts[1]}---\n{header}{parts[2]}"


def update_instruction_file(instruction_path: Path, bundle: PluginBundle) -> list[Path]:
    """Generate or update the runtime's instruction file with the BrainPalace
    section.

    Uses HTML comment markers for idempotent updates — running this
    multiple times will replace the existing section rather than
    duplicating it.

    Returns list of created/updated paths.
    """
    # Build skill table
    skill_rows: list[str] = []
    for cmd in bundle.commands:
        skill_rows.append(f"| {cmd.name} | {cmd.description} |")
    for agent in bundle.agents:
        skill_rows.append(f"| {agent.name} | {agent.description} |")
    for skill in bundle.skills:
        skill_rows.append(f"| {skill.name} | {skill.description} |")

    skill_table = "\n".join(skill_rows) if skill_rows else "| (none) | - |"

    section = INSTRUCTION_FILE_SECTION.format(
        start_marker=INSTRUCTION_FILE_START,
        end_marker=INSTRUCTION_FILE_END,
        skill_table=skill_table,
    )

    if instruction_path.exists():
        existing = instruction_path.read_text(encoding="utf-8")
        if INSTRUCTION_FILE_START in existing and INSTRUCTION_FILE_END in existing:
            # Replace existing section
            start_idx = existing.index(INSTRUCTION_FILE_START)
            end_idx = existing.index(INSTRUCTION_FILE_END) + len(INSTRUCTION_FILE_END)
            updated = existing[:start_idx] + section + existing[end_idx:]
            instruction_path.write_text(updated, encoding="utf-8")
        else:
            # Append section
            instruction_path.write_text(
                existing.rstrip() + "\n\n" + section + "\n",
                encoding="utf-8",
            )
    else:
        # Create new file
        content = f"# {instruction_path.name}\n\n{section}\n"
        instruction_path.parent.mkdir(parents=True, exist_ok=True)
        instruction_path.write_text(content, encoding="utf-8")

    return [instruction_path]


class SkillInstructionConverter:
    """Converter for runtimes with skill dirs + a project-root instruction file.

    Delegates skill-directory creation to SkillRuntimeConverter and adds
    generation of an idempotently-updated instruction file (AGENTS.md,
    QWEN.md, ...) at the project root, with per-skill invocation headers.

    Subclasses set three class attributes: `runtime_type`,
    `instruction_filename`, `header_label`.
    """

    runtime_type: RuntimeType
    instruction_filename: str
    header_label: str

    def __init__(self) -> None:
        self._base = SkillRuntimeConverter()

    def convert_command(self, command: PluginCommand) -> str:
        """Convert command with the runtime's invocation guidance header."""
        base_content = self._base.convert_command(command)
        return add_instruction_header(base_content, command.name, self.header_label)

    def convert_agent(self, agent: PluginAgent) -> str:
        """Convert agent with the runtime's invocation guidance header."""
        base_content = self._base.convert_agent(agent)
        return add_instruction_header(base_content, agent.name, self.header_label)

    def convert_skill(self, skill: PluginSkill) -> str:
        """Convert skill with the runtime's invocation guidance header."""
        return self._base.convert_skill(skill)

    def install(
        self,
        bundle: PluginBundle,
        target_dir: Path,
        scope: Scope,
        project_root: Path | None = None,
    ) -> list[Path]:
        """Install skills and generate the runtime's instruction file.

        Delegates skill-directory creation to the base converter, then
        generates/updates the instruction file at the project root.

        Args:
            bundle: Parsed plugin bundle.
            target_dir: Where to write skill directories.
            scope: Project-level or global installation.
            project_root: Project root for the instruction file. If None,
                derived from target_dir for project scope.
        """
        # Install skill directories via base converter
        created = self._base.install(bundle, target_dir, scope)

        # Re-write command and agent SKILL.md files with the runtime's headers
        for cmd in bundle.commands:
            skill_name = _skill_dir_name(cmd.name)
            skill_file = target_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                skill_file.write_text(self.convert_command(cmd), encoding="utf-8")

        for agent in bundle.agents:
            skill_name = _skill_dir_name(agent.name)
            skill_file = target_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                skill_file.write_text(self.convert_agent(agent), encoding="utf-8")

        # Generate the instruction file at the project root
        if project_root is None:
            if scope == Scope.PROJECT:
                # <dot>/skills/brainpalace -> project root (3 levels up)
                project_root = target_dir.parent.parent.parent
            else:
                project_root = Path.cwd()

        instruction_path = project_root / self.instruction_filename
        try:
            instruction_files = update_instruction_file(instruction_path, bundle)
            created.extend(instruction_files)
        except OSError as exc:
            logger.warning("Could not write %s: %s", self.instruction_filename, exc)

        return created

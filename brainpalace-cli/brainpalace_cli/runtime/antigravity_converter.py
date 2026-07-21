"""Antigravity (agy) runtime converter.

Antigravity is a named preset built on the generic skill-runtime converter,
mirroring CodexConverter: it installs to `.agents/skills/brainpalace/` and
generates an AGENTS.md file at the project root with BrainPalace guidance.

Key differences from base SkillRuntimeConverter:
    - Default install dir: .agents/skills/brainpalace/ (project),
      ~/.gemini/config/skills/brainpalace/ (global) — the one path
      agy/CLI/IDE all honour.
    - AGENTS.md generated at project root (idempotent via HTML comment
      markers), identical mechanism to Codex.
    - Skills include invocation guidance headers.

No tool-name remap: skill bodies reference the `brainpalace` CLI, not Claude
tool names (Bash/Read/Write), so — like Codex — there is nothing to
translate. Do not wire this converter through `tool_maps.map_tools`.

Built on the shared `SkillInstructionConverter` base
(runtime/skill_instruction_converter.py), which holds all of the above
logic parameterized by (runtime_type, instruction_filename, header_label).
"""

from pathlib import Path

from brainpalace_cli.runtime.skill_instruction_converter import (
    INSTRUCTION_FILE_END as AGENTS_MD_END,
)
from brainpalace_cli.runtime.skill_instruction_converter import (
    INSTRUCTION_FILE_START as AGENTS_MD_START,
)
from brainpalace_cli.runtime.skill_instruction_converter import (
    SkillInstructionConverter,
    add_instruction_header,
    update_instruction_file,
)
from brainpalace_cli.runtime.types import PluginBundle, RuntimeType

__all__ = [
    "AGENTS_MD_END",
    "AGENTS_MD_START",
    "AntigravityConverter",
]


class AntigravityConverter(SkillInstructionConverter):
    """Converter for Antigravity (agy) runtime (skill-runtime preset).

    Delegates skill-directory creation to SkillRuntimeConverter and
    adds Antigravity-specific AGENTS.md generation, mirroring Codex.
    """

    runtime_type = RuntimeType.ANTIGRAVITY
    instruction_filename = "AGENTS.md"
    header_label = "Antigravity"


def _add_antigravity_header(content: str, name: str) -> str:
    """Add an Antigravity invocation guidance header after the frontmatter.

    Inserts a brief note about how to invoke this skill in Antigravity.
    """
    return add_instruction_header(content, name, "Antigravity")


def _update_agents_md(agents_md_path: Path, bundle: PluginBundle) -> list[Path]:
    """Generate or update AGENTS.md with BrainPalace section.

    Uses HTML comment markers for idempotent updates — running this
    multiple times will replace the existing section rather than
    duplicating it.

    Returns list of created/updated paths.
    """
    return update_instruction_file(agents_md_path, bundle)

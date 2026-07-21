"""Kimi CLI runtime converter.

Kimi CLI is a named preset built on the generic skill-runtime converter,
mirroring CodexConverter: it installs skills as `SKILL.md` dirs and
generates an AGENTS.md file at the project root with BrainPalace guidance
(Kimi injects AGENTS.md content via `KIMI_AGENTS_MD`).

Key differences from base SkillRuntimeConverter:
    - Default install dir: .kimi-code/skills/brainpalace/ (project),
      ~/.kimi-code/skills/brainpalace/ (global, honours $KIMI_CODE_HOME) —
      NOTE: the project-scope subdir is an assumption (research only
      confirmed the global `~/.kimi-code/skills/` layout); Kimi MCP
      (Phase B, `install-mcp --client kimi`) instead writes to `~/.kimi/`,
      a real home-dir split between skills and MCP config in Kimi.
    - AGENTS.md generated at project root (idempotent via HTML comment
      markers), identical mechanism to Codex.
    - Skills include invocation guidance headers.

No tool-name remap: skill bodies reference the `brainpalace` CLI, not Claude
tool names (Bash/Read/Write), so — like Codex — there is nothing to
translate.

Built on the shared `SkillInstructionConverter` base
(runtime/skill_instruction_converter.py), which holds all of the above
logic parameterized by (runtime_type, instruction_filename, header_label).
"""

from brainpalace_cli.runtime.skill_instruction_converter import (
    SkillInstructionConverter,
)
from brainpalace_cli.runtime.types import RuntimeType

__all__ = ["KimiConverter"]


class KimiConverter(SkillInstructionConverter):
    """Converter for Kimi CLI runtime (skill-runtime preset).

    Delegates skill-directory creation to SkillRuntimeConverter and
    adds Kimi-specific AGENTS.md generation, mirroring Codex.
    """

    runtime_type = RuntimeType.KIMI
    instruction_filename = "AGENTS.md"
    header_label = "Kimi"

"""Qwen Code runtime converter.

Qwen Code is a named preset built on the generic skill-runtime converter,
mirroring CodexConverter: it installs skills as `SKILL.md` dirs and
generates a QWEN.md file at the project root with BrainPalace guidance
(Qwen Code's hierarchical memory; it also reads GEMINI.md, but BrainPalace
only ever writes QWEN.md).

Key differences from base SkillRuntimeConverter:
    - Default install dir: .qwen/skills/brainpalace/ (project),
      ~/.qwen/skills/brainpalace/ (global).
    - QWEN.md (not AGENTS.md) generated at project root (idempotent via
      HTML comment markers), identical mechanism to Codex.
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

__all__ = ["QwenConverter"]


class QwenConverter(SkillInstructionConverter):
    """Converter for Qwen Code runtime (skill-runtime preset).

    Delegates skill-directory creation to SkillRuntimeConverter and
    adds Qwen-specific QWEN.md generation, mirroring Codex.
    """

    runtime_type = RuntimeType.QWEN
    instruction_filename = "QWEN.md"
    header_label = "Qwen"

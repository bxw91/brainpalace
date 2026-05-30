"""Runtime converter infrastructure for multi-runtime plugin support."""

from brainpalace_cli.runtime.converter_base import RuntimeConverter
from brainpalace_cli.runtime.parser import (
    parse_agent,
    parse_command,
    parse_frontmatter,
    parse_plugin_dir,
    parse_scripts,
    parse_skill,
    parse_templates,
)
from brainpalace_cli.runtime.tool_maps import (
    CLAUDE_TOOLS,
    GEMINI_TOOLS,
    OPENCODE_TOOLS,
    map_tool_name,
    map_tools,
)
from brainpalace_cli.runtime.types import (
    PluginAgent,
    PluginBundle,
    PluginCommand,
    PluginManifest,
    PluginParameter,
    PluginScript,
    PluginSkill,
    PluginTemplate,
    RuntimeType,
    Scope,
    TriggerPattern,
)

__all__ = [
    "CLAUDE_TOOLS",
    "GEMINI_TOOLS",
    "OPENCODE_TOOLS",
    "PluginAgent",
    "PluginBundle",
    "PluginCommand",
    "PluginManifest",
    "PluginParameter",
    "PluginScript",
    "PluginSkill",
    "PluginTemplate",
    "RuntimeConverter",
    "RuntimeType",
    "Scope",
    "TriggerPattern",
    "map_tool_name",
    "map_tools",
    "parse_agent",
    "parse_command",
    "parse_frontmatter",
    "parse_plugin_dir",
    "parse_scripts",
    "parse_skill",
    "parse_templates",
]

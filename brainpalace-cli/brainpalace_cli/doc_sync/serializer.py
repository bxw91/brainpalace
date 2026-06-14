# brainpalace-cli/brainpalace_cli/doc_sync/serializer.py
"""Byte-stable rendering of machine-owned regions. Ordering is an explicit policy:
flags in DEFINITION order (to match --help). No YAML lib — we emit a fixed, minimal
shape so output never depends on a dumper's defaults."""

from __future__ import annotations

from brainpalace_cli.doc_sync.facts import CommandFact
from brainpalace_cli.doc_sync.markers import CLOSE, OPEN_FMT


def _yaml_scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return '""'
    return str(v)


# YAML 1.1 boolean-ish bare scalars that safe_load coerces away from the literal
# string (e.g. `name: yes` parses to True). Names matching these MUST be quoted so
# the doc round-trips back to the original flag name.
_YAML_BOOLISH = frozenset(
    {"yes", "no", "true", "false", "on", "off", "y", "n", "null", "none", "~"}
)


def _yaml_name(name: str) -> str:
    if name.lower() in _YAML_BOOLISH:
        return f'"{name}"'
    return name


def render_params_yaml(cmd: CommandFact) -> str:
    lines = ["parameters:"]
    for f in cmd.flags:  # definition order, as-stored
        lines.append(f"  - name: {_yaml_name(f.name)}")
        lines.append(f"    type: {f.type}")
        lines.append(f"    required: {'true' if f.required else 'false'}")
        lines.append(f"    default: {_yaml_scalar(f.default)}")
    return "\n".join(lines)


def render_flags_section(cmd: CommandFact) -> str:
    """A complete '### Flags' section wrapping the generated table in markers."""
    table = render_flags_table(cmd)
    return f"### Flags\n{OPEN_FMT.format(name='flags')}\n{table}\n{CLOSE}"


def render_flags_table(cmd: CommandFact) -> str:
    rows = [
        "| Flag | Type | Default | Description |",
        "|------|------|---------|-------------|",
    ]
    for f in cmd.flags:  # definition order
        desc = f.description.replace("|", "\\|") or "—"
        rows.append(f"| --{f.name} | {f.type} | {_yaml_scalar(f.default)} | {desc} |")
    return "\n".join(rows)


def render_mcp_tools_table(tools: list[str]) -> str:
    rows = ["| Tool | Description |", "|------|-------------|"]
    for t in sorted(tools):  # alpha order
        rows.append(f"| `{t}` |  |")
    return "\n".join(rows)


def render_modes_table(modes: list[str]) -> str:
    rows = ["| Mode | Description |", "|------|-------------|"]
    for m in modes:  # definition order (matches the Choice)
        rows.append(
            f"| `{m}` |  |"
        )  # description is human prose, left blank by generator
    return "\n".join(rows)

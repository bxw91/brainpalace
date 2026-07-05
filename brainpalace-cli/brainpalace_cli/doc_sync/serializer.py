# brainpalace-cli/brainpalace_cli/doc_sync/serializer.py
"""Byte-stable rendering of machine-owned regions. Ordering is an explicit policy:
flags in DEFINITION order (to match --help). No YAML lib — we emit a fixed, minimal
shape so output never depends on a dumper's defaults."""

from __future__ import annotations

from typing import Any

from brainpalace_cli.doc_sync.facts import CommandFact
from brainpalace_cli.doc_sync.markers import CLOSE, OPEN_FMT
from brainpalace_cli.doc_sync.mode_meta import resolve_meta


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


def _esc(cell: str) -> str:
    return cell.replace("|", "\\|")


def render_modes_table(modes: list[str]) -> str:
    """2-col `| Mode | Description |` shape (plugin brainpalace-query.md,
    docs/API_REFERENCE.md). Description filled from the single-source MODE_META —
    resolve_meta raises if a live mode has no entry, so this can never silently
    render blank."""
    rows = ["| Mode | Description |", "|------|-------------|"]
    for m, meta in resolve_meta(modes):  # definition order (matches the Choice)
        rows.append(f"| `{m}` | {_esc(meta.description)} |")
    return "\n".join(rows)


def render_modes_grid(modes: list[str]) -> str:
    """README shape: `| Mode | Best For | Example Query |`, mode UPPERCASE."""
    rows = [
        "| Mode | Best For | Example Query |",
        "|------|----------|---------------|",
    ]
    for m, meta in resolve_meta(modes):
        rows.append(
            f'| `{m.upper()}` | {_esc(meta.best_for)} | "{_esc(meta.example)}" |'
        )
    return "\n".join(rows)


def render_modes_commands(modes: list[str]) -> str:
    """USER_GUIDE shape: `| Command | Description | Best For |`. hybrid is the
    default mode, so its command cell omits `--mode hybrid`."""
    rows = [
        "| Command | Description | Best For |",
        "|---------|-------------|----------|",
    ]
    for m, meta in resolve_meta(modes):
        cmd = (
            "/brainpalace-query" if m == "hybrid" else f"/brainpalace-query --mode {m}"
        )
        rows.append(f"| `{cmd}` | {_esc(meta.description)} | {_esc(meta.best_for)} |")
    return "\n".join(rows)


def render_provider_table(
    providers: dict[str, dict[str, dict[str, Any]]], kind: str
) -> str:
    """Provider table for one kind (embedding/summarization/reranker) from the
    canonical PROVIDERS registry. Provider order = registry order; the first model
    is the recommended default."""
    rows = [
        "| Provider | API key env var | Models (default first) |",
        "|----------|-----------------|------------------------|",
    ]
    for provider, info in providers.get(kind, {}).items():
        env = info.get("default_api_key_env")
        env_cell = f"`{env}`" if env else "_(none — local)_"
        models = ", ".join(f"`{m}`" for m in info.get("models", [])) or "—"
        rows.append(f"| `{provider}` | {env_cell} | {models} |")
    return "\n".join(rows)


def render_install_dirs_table(install_dirs: dict[str, dict[str, str]]) -> str:
    """Runtime install-path table from install_agent.INSTALL_DIRS (runtime order)."""
    rows = [
        "| Runtime | Project dir | Global dir |",
        "|---------|-------------|------------|",
    ]
    for runtime, scopes in install_dirs.items():
        project = scopes.get("project", "—")
        glob = scopes.get("global", "—")
        rows.append(f"| `{runtime}` | `{project}` | `{glob}` |")
    return "\n".join(rows)

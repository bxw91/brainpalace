"""Config commands for viewing and managing BrainPalace configuration."""

import json
import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

from brainpalace_cli.config_migrate import (
    MigrationResult,
    diff_config_file,
    migrate_config_file,
)
from brainpalace_cli.config_schema import (
    format_validation_errors,
    validate_config_file,
)
from brainpalace_cli.providers import recommended_model
from brainpalace_cli.xdg_paths import get_xdg_config_dir

console = Console()


def _find_config_file() -> Path | None:
    """Find the configuration file in standard locations.

    Search order:
    1. BRAINPALACE_CONFIG environment variable
    2. State directory config.yaml (if BRAINPALACE_STATE_DIR set)
    3. Current directory config.yaml
    4. Walk up from CWD: .brainpalace/config.yaml (or legacy path)
    5. XDG config ~/.config/brainpalace/config.yaml (preferred)
    6. Legacy ~/.brainpalace/config.yaml (deprecated, prints warning)

    Returns:
        Path to config file or None if not found
    """
    # 1. Environment variable override
    env_config = os.getenv("BRAINPALACE_CONFIG")
    if env_config:
        path = Path(env_config)
        if path.exists():
            return path

    # 2. State directory
    state_dir = os.getenv("BRAINPALACE_STATE_DIR") or os.getenv("DOC_SERVE_STATE_DIR")
    if state_dir:
        state_config = Path(state_dir) / "config.yaml"
        if state_config.exists():
            return state_config

    # 3. Current directory
    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        return cwd_config

    # 4. Walk up from CWD looking for .brainpalace/ or legacy .claude/brainpalace/
    current = Path.cwd()
    root = Path(current.anchor)
    while current != root:
        new_config = current / ".brainpalace" / "config.yaml"
        if new_config.exists():
            return new_config
        legacy_config = current / ".claude" / "brainpalace" / "config.yaml"
        if legacy_config.exists():
            return legacy_config
        current = current.parent

    # 5. XDG config (checked before legacy per XDG standard)
    xdg_config_path = get_xdg_config_dir() / "config.yaml"
    if xdg_config_path.exists():
        return xdg_config_path

    xdg_alt = get_xdg_config_dir() / "brainpalace.yaml"
    if xdg_alt.exists():
        return xdg_alt

    # 6. Legacy path ~/.brainpalace/ (deprecated, fallback only)
    home_config = Path.home() / ".brainpalace" / "config.yaml"
    if home_config.exists():
        sys.stderr.write(
            "Warning: Using legacy config path ~/.brainpalace/config.yaml. "
            "Run 'brainpalace start' to migrate to ~/.config/brainpalace/.\n"
        )
        return home_config

    home_alt = Path.home() / ".brainpalace" / "brainpalace.yaml"
    if home_alt.exists():
        sys.stderr.write(
            "Warning: Using legacy config path ~/.brainpalace/brainpalace.yaml. "
            "Run 'brainpalace start' to migrate to ~/.config/brainpalace/.\n"
        )
        return home_alt

    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML configuration file."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _lemma_languages_hint() -> str:
    """Return a parenthetical listing the BM25 lemma languages — e.g.
    ' — currently: Croatian/Serbian'.  Read live from the server registry so
    the string never drifts.  Returns '' when the server can't be imported."""
    try:
        import importlib

        registry = importlib.import_module(
            "brainpalace_server.indexing.text_analysis.registry"
        )
        label = str(getattr(registry, "lemma_language_label", lambda: "")())
    except Exception:  # noqa: BLE001
        return ""
    return f" — currently: {label}" if label else ""


def _resolve_wizard_config_path() -> Path:
    """Resolve output path for config wizard.

    Returns:
        Path to .brainpalace/config.yaml in nearest existing state dir,
        or creates .brainpalace/config.yaml in current working directory.
    """
    current = Path.cwd()
    root = Path(current.anchor)

    while True:
        state_dir = current / ".brainpalace"
        if state_dir.is_dir():
            return state_dir / "config.yaml"

        if current == root:
            break
        current = current.parent

    return Path.cwd() / ".brainpalace" / "config.yaml"


@click.group("config")
def config_group() -> None:
    """View and manage BrainPalace configuration.

    \b
    Commands:
      show     - Display active configuration
      path     - Show config file location
      wizard   - Create/update config interactively
      validate - Validate config against schema
      migrate  - Upgrade config to current schema
      diff     - Preview what migrate would change
    """
    pass


@config_group.command("wizard")
@click.option(
    "--global",
    "global_",
    is_flag=True,
    help="Edit the global ~/.config/brainpalace/config.yaml (XDG) instead of the "
    "current project's .brainpalace/.",
)
@click.option(
    "--chat-summarizer",
    "chat_summarizer",
    type=click.Choice(["plugin", "provider", "auto"]),
    default="auto",
    help="[Deprecated, no-op] Retained for back-compat; the session engine "
    "('auto') is resolved at runtime and is not set here.",
)
@click.pass_context
def wizard(ctx: click.Context, global_: bool, chat_summarizer: str) -> None:
    """Edit BrainPalace configuration (alias of `brainpalace init`'s editor).

    On an already-initialized project this opens the review editor.  On a FRESH
    project it delegates to `init` (config bootstrap; no server start), which
    creates .brainpalace/ -- `wizard` is now `init` in edit mode.
    """
    from brainpalace_cli.commands.init import init_command

    # Check existing config for validation issues before prompting. First
    # auto-migrate away dead/renamed keys (api:, session_extraction.mode, …) so
    # a stranded pre-rename config is fixed rather than merely warned about; only
    # residual real errors are then surfaced.
    existing_config = _find_config_file()
    if existing_config:
        migration = migrate_config_file(existing_config)
        if not migration.already_current:
            console.print("\n[cyan]Migrated deprecated config keys:[/]")
            for change in migration.changes:
                console.print(f"  [cyan]->[/] {change}")
        existing_errors = validate_config_file(existing_config)
        if existing_errors:
            console.print(
                "\n[bold yellow]Warning:[/] Existing config has validation issues:"
            )
            console.print(format_validation_errors(existing_errors))
            console.print()

    # Delegate to the single unified editor.  `start=False` keeps wizard a pure
    # config editor; ctx.invoke fills every other init param from its Click
    # default (all init options have defaults).
    ctx.invoke(init_command, global_=global_, start=False)


@config_group.command("show")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def show_config(json_output: bool) -> None:
    """Display the active provider configuration.

    Shows which config file is being used and the current provider settings
    for embedding, summarization, and reranking.

    \b
    Examples:
      brainpalace config show           # Rich formatted output
      brainpalace config show --json    # JSON output for scripting
    """
    config_path = _find_config_file()

    if json_output:
        output: dict[str, Any] = {
            "config_file": str(config_path) if config_path else None,
            "config_source": "file" if config_path else "defaults",
        }

        if config_path:
            config = _load_yaml(config_path)
            output["embedding"] = config.get("embedding", {})
            output["summarization"] = config.get("summarization", {})
            output["reranker"] = config.get("reranker", {})
        else:
            output["embedding"] = {
                "provider": "openai",
                "model": recommended_model("embedding", "openai"),
            }
            output["summarization"] = {
                "provider": "anthropic",
                "model": recommended_model("summarization", "anthropic"),
            }

        click.echo(json.dumps(output, indent=2))
        return

    # Rich formatted output
    if config_path:
        console.print(f"\n[bold]Config file:[/] {config_path}\n")
        config = _load_yaml(config_path)
    else:
        console.print("\n[yellow]No config file found, using defaults[/]\n")
        config = {}

    # Embedding provider
    embedding = config.get("embedding", {})
    embed_table = Table(title="Embedding Provider", show_header=False)
    embed_table.add_column("Setting", style="cyan")
    embed_table.add_column("Value")
    embed_table.add_row("Provider", embedding.get("provider", "openai"))
    embed_table.add_row(
        "Model", embedding.get("model", recommended_model("embedding", "openai"))
    )
    embed_table.add_row("API Key Env", embedding.get("api_key_env", "OPENAI_API_KEY"))
    if embedding.get("base_url"):
        embed_table.add_row("Base URL", embedding["base_url"])
    console.print(embed_table)

    # Summarization provider
    summarization = config.get("summarization", {})
    summ_table = Table(title="Summarization Provider", show_header=False)
    summ_table.add_column("Setting", style="cyan")
    summ_table.add_column("Value")
    summ_table.add_row("Provider", summarization.get("provider", "anthropic"))
    summ_table.add_row(
        "Model",
        summarization.get("model", recommended_model("summarization", "anthropic")),
    )
    summ_table.add_row(
        "API Key Env", summarization.get("api_key_env", "ANTHROPIC_API_KEY")
    )
    if summarization.get("base_url"):
        summ_table.add_row("Base URL", summarization["base_url"])
    console.print(summ_table)

    # Reranker (if configured)
    reranker = config.get("reranker", {})
    if reranker:
        rerank_table = Table(title="Reranker Provider", show_header=False)
        rerank_table.add_column("Setting", style="cyan")
        rerank_table.add_column("Value")
        rerank_table.add_row(
            "Provider", reranker.get("provider", "sentence-transformers")
        )
        rerank_table.add_row(
            "Model", reranker.get("model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        )
        if reranker.get("base_url"):
            rerank_table.add_row("Base URL", reranker["base_url"])
        console.print(rerank_table)

    console.print()


@config_group.command("unset")
@click.argument("dotpaths", nargs=-1, required=True)
@click.option(
    "--global",
    "global_",
    is_flag=True,
    help="Unset from the global XDG config instead of the project config.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def unset_config(dotpaths: tuple[str, ...], global_: bool, json_output: bool) -> None:
    """Remove KEY(s) from config so they inherit the layered default.

    Each KEY is a dotted path (e.g. ``bm25.language``, ``git_indexing.enabled``).
    Removing a project value makes BrainPalace fall back to the global config,
    then the built-in code default — config resolves ``project < global < code``.

    \b
    Examples:
      brainpalace config unset bm25.language        # inherit from global/code
      brainpalace config unset git_indexing.enabled session_indexing.enabled
      brainpalace config unset --global reranker.enabled
    """
    from brainpalace_cli.config_resolve import (
        global_config_path,
        inherited,
        read_yaml,
        unset_dotpath,
    )

    target = global_config_path() if global_ else _resolve_wizard_config_path()
    data = read_yaml(target)
    removed = [dp for dp in dotpaths if unset_dotpath(data, dp)]
    if removed:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    glob = {} if global_ else read_yaml(global_config_path())
    if json_output:
        result = {}
        for dp in dotpaths:
            entry: dict[str, Any] = {"removed": dp in removed}
            if dp in removed and not global_:
                val, src = inherited(dp, glob)
                entry["now_uses"] = {"value": val, "source": src}
            result[dp] = entry
        click.echo(json.dumps(result, indent=2))
        return

    for dp in dotpaths:
        if dp not in removed:
            console.print(f"[dim]{dp} was not set; nothing to unset.[/]")
        elif global_:
            console.print(f"[green]Unset[/] {dp} from the global config.")
        else:
            val, src = inherited(dp, glob)
            console.print(
                f"[green]Unset[/] {dp} — will now use [cyan]{val}[/] from {src}."
            )


@config_group.command("path")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def config_path(json_output: bool) -> None:
    """Show the path to the active config file.

    \b
    Examples:
      brainpalace config path           # Print config file path
      brainpalace config path --json    # JSON output
    """
    config_path = _find_config_file()

    if json_output:
        click.echo(
            json.dumps(
                {
                    "config_file": str(config_path) if config_path else None,
                    "exists": config_path.exists() if config_path else False,
                }
            )
        )
        return

    if config_path:
        console.print(f"[green]{config_path}[/]")
    else:
        console.print("[yellow]No config file found[/]")


@config_group.command("validate")
@click.option(
    "--file",
    "config_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to config file (default: auto-detect)",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def validate_config(config_file: str | None, json_output: bool) -> None:
    """Validate config.yaml against the BrainPalace schema.

    Checks for unknown keys, invalid provider values, deprecated fields,
    and type errors. Reports line numbers and fix suggestions.

    \b
    Examples:
      brainpalace config validate
      brainpalace config validate --file ./my-config.yaml
      brainpalace config validate --json
    """
    if config_file is not None:
        path: Path | None = Path(config_file)
    else:
        path = _find_config_file()

    if path is None:
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "valid": None,
                        "config_file": None,
                        "errors": [],
                        "message": "No config file found",
                    }
                )
            )
        else:
            console.print("[yellow]No config file found. Nothing to validate.[/]")
        sys.exit(0)

    errors = validate_config_file(path)

    if json_output:
        output: dict[str, Any] = {
            "valid": len(errors) == 0,
            "config_file": str(path),
            "errors": [
                {
                    "field": e.field,
                    "message": e.message,
                    "line_number": e.line_number,
                    "suggestion": e.suggestion,
                }
                for e in errors
            ],
        }
        click.echo(json.dumps(output, indent=2))
        if errors:
            sys.exit(1)
        return

    if not errors:
        console.print(f"[green]Config is valid[/] ({path})")
        sys.exit(0)

    console.print(format_validation_errors(errors))
    sys.exit(1)


@config_group.command("migrate")
@click.option(
    "--file",
    "config_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to config file (default: auto-detect)",
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would change without modifying"
)
def migrate_config_cmd(config_file: str | None, dry_run: bool) -> None:
    """Migrate config.yaml to the current schema version.

    Upgrades deprecated keys and restructures config sections.
    Use --dry-run to preview changes without modifying the file.

    \b
    Examples:
      brainpalace config migrate
      brainpalace config migrate --dry-run
      brainpalace config migrate --file ./old-config.yaml
    """
    if config_file is not None:
        path: Path | None = Path(config_file)
    else:
        path = _find_config_file()

    if path is None:
        console.print("[yellow]No config file found.[/]")
        sys.exit(0)

    if dry_run:
        diff = diff_config_file(path)
        if diff:
            console.print(diff)
        else:
            console.print("[green]Config is already up to date. No changes needed.[/]")
        sys.exit(0)

    result: MigrationResult = migrate_config_file(path)
    if result.already_current:
        console.print("[green]Config is already up to date[/]")
        sys.exit(0)

    for change in result.changes:
        console.print(f"  [cyan]->[/] {change}")
    console.print(f"\n[green]Config migrated successfully[/] ({path})")


@config_group.command("diff")
@click.option(
    "--file",
    "config_file",
    type=click.Path(exists=True),
    default=None,
    help="Path to config file (default: auto-detect)",
)
def diff_config_cmd(config_file: str | None) -> None:
    """Show what 'config migrate' would change.

    Displays a unified diff of the current config vs the migrated version.

    \b
    Examples:
      brainpalace config diff
      brainpalace config diff --file ./config.yaml
    """
    if config_file is not None:
        path: Path | None = Path(config_file)
    else:
        path = _find_config_file()

    if path is None:
        console.print("[yellow]No config file found.[/]")
        sys.exit(0)

    diff = diff_config_file(path)
    if not diff:
        console.print("[green]Config is already up to date. No changes needed.[/]")
        sys.exit(0)

    for line in diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            console.print(f"[bold]{line}[/]")
        elif line.startswith("-"):
            console.print(f"[red]{line}[/]")
        elif line.startswith("+"):
            console.print(f"[green]{line}[/]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/]")
        else:
            console.print(line)

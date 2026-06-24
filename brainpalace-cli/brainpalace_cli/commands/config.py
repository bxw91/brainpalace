"""Config commands for viewing and managing BrainPalace configuration."""

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

from brainpalace_cli.commands.plugin_detect import claude_plugin_installed
from brainpalace_cli.config_migrate import (
    MigrationResult,
    diff_config_file,
    migrate_config_file,
)
from brainpalace_cli.config_schema import (
    format_validation_errors,
    validate_config_file,
)
from brainpalace_cli.providers import PROVIDERS, recommended_model
from brainpalace_cli.xdg_paths import get_xdg_config_dir

console = Console()


# Recommended model per provider — sourced from the canonical provider
# descriptor (brainpalace_cli.providers) so the wizard, the dashboard, and the
# README never drift. First model in each provider's list is the recommendation.
EMBEDDING_DEFAULT_MODELS = {
    prov: PROVIDERS["embedding"][prov]["models"][0] for prov in PROVIDERS["embedding"]
}

SUMMARIZATION_DEFAULT_MODELS = {
    prov: PROVIDERS["summarization"][prov]["models"][0]
    for prov in PROVIDERS["summarization"]
}


def _find_available_api_port(start: int = 8000, end: int = 8300) -> int:
    """Find an available TCP port in an inclusive range."""
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise click.ClickException(f"No available ports found in range {start}-{end}")


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
    """`" — currently: Croatian/Serbian"` listing the languages the lemma BM25
    engine actually supports, read live from the bundled server's analyzer
    registry (the single source of truth) so the prompt never hardcodes the list.

    Resolved dynamically via ``getattr`` so an older bundled server that predates
    ``lemma_language_label`` degrades to an empty hint instead of breaking. Empty
    string if the server can't be imported."""
    try:
        import importlib

        registry = importlib.import_module(
            "brainpalace_server.indexing.text_analysis.registry"
        )
        label = str(getattr(registry, "lemma_language_label", lambda: "")())
    except Exception:
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
    help="Write to the global ~/.config/brainpalace/config.yaml (XDG) that all "
    "projects inherit, instead of the current project's .brainpalace/.",
)
@click.option(
    "--chat-summarizer",
    "chat_summarizer",
    type=click.Choice(["plugin", "provider", "auto"]),
    default="auto",
    help="Who summarizes chat/session transcripts: 'plugin' (free on the Claude "
    "Code subscription), 'provider' (the summarization provider's API), or "
    "'auto' (detect the plugin). Wording-only — does NOT change the written "
    "config or the session engine (engine stays 'auto', resolved at runtime).",
)
def wizard(global_: bool, chat_summarizer: str) -> None:
    """Interactive configuration wizard for BrainPalace providers."""
    # Check existing config for validation issues before prompting
    existing_config = _find_config_file()
    if existing_config:
        existing_errors = validate_config_file(existing_config)
        if existing_errors:
            console.print(
                "\n[bold yellow]Warning:[/] Existing config has validation issues:"
            )
            console.print(format_validation_errors(existing_errors))
            console.print()

    # Prefill prompt defaults from the saved GLOBAL config so re-running the
    # wizard (e.g. during install/update) keeps current choices on Enter instead
    # of silently resetting to shipped defaults. Missing keys fall back to the
    # static default.
    _global_cfg = get_xdg_config_dir() / "config.yaml"
    prefill = _load_yaml(_global_cfg) if _global_cfg.is_file() else {}

    def _prev(dotpath: str, fallback: Any) -> Any:
        node: Any = prefill
        for seg in dotpath.split("."):
            if not isinstance(node, dict) or seg not in node:
                return fallback
            node = node[seg]
        return node if node is not None else fallback

    prev_embed_provider = _prev("embedding.provider", "openai")
    prev_summ_provider = _prev("summarization.provider", None)

    embed_provider: str = click.prompt(
        "\nEmbedding provider",
        type=click.Choice(["openai", "ollama", "cohere"]),
        default=(
            prev_embed_provider
            if prev_embed_provider in ("openai", "ollama", "cohere")
            else "openai"
        ),
    )
    embed_model: str = click.prompt(
        "\nEmbedding model",
        default=(
            _prev("embedding.model", EMBEDDING_DEFAULT_MODELS[embed_provider])
            if embed_provider == prev_embed_provider
            else EMBEDDING_DEFAULT_MODELS[embed_provider]
        ),
    )

    batch_size: str | None = None
    request_delay_ms: int | None = None
    if embed_provider == "ollama":
        prev_batch = str(_prev("embedding.params.batch_size", "10"))
        batch_size = click.prompt(
            "\nBatch size",
            type=click.Choice(["1", "5", "10", "20", "50", "100"]),
            default=(
                prev_batch
                if prev_batch in ("1", "5", "10", "20", "50", "100")
                else "10"
            ),
        )
        request_delay_ms = click.prompt(
            "\nRequest delay between batches (ms, 0=none)",
            type=click.IntRange(min=0),
            default=int(_prev("embedding.params.request_delay_ms", 0)),
        )

    # Default summarization to the embedding provider when it can also
    # summarize (openai, ollama); otherwise fall back to whichever
    # summarization API key is already set in the environment, else anthropic.
    if embed_provider in ("openai", "ollama"):
        summ_default = embed_provider
    elif os.getenv("OPENAI_API_KEY"):
        summ_default = "openai"
    elif os.getenv("ANTHROPIC_API_KEY"):
        summ_default = "anthropic"
    elif os.getenv("GOOGLE_API_KEY"):
        summ_default = "gemini"
    else:
        summ_default = "anthropic"
    # A previously-saved global provider wins over the env/heuristic default.
    if prev_summ_provider in ("anthropic", "openai", "ollama", "gemini"):
        summ_default = prev_summ_provider
    # Resolve who handles CHAT/session summaries so we can word the prompt
    # accordingly. The provider below is for CODE either way; the plugin (when
    # present) adds chat summaries FREE via a Haiku subagent. Wording-only — the
    # written config and the session engine ('auto') are unchanged.
    if chat_summarizer == "auto":
        chat_by_plugin = claude_plugin_installed()
    else:
        chat_by_plugin = chat_summarizer == "plugin"

    if chat_by_plugin:
        click.echo(
            "\nChat-session summarization will run through Claude Code plugin (using"
            "\nHaiku subagent) — so this provider is for CODE only."
        )
    else:
        click.echo(
            "\n"
            + click.style("Chat-session summarization is OFF.", fg="red", bold=True)
            + " Enable it by installing the Claude"
            " Code\nplugin (free, Haiku subagent), or set SESSION_DISTILL_ENABLED=true"
            " to use\nthe code summarization provider/model below."
        )

    summ_provider: str = click.prompt(
        "\nCode summarization provider",
        type=click.Choice(["anthropic", "openai", "ollama", "gemini"]),
        default=summ_default,
    )
    summ_model: str = click.prompt(
        "\nCode summarization model",
        default=(
            _prev("summarization.model", SUMMARIZATION_DEFAULT_MODELS[summ_provider])
            if summ_provider == prev_summ_provider
            else SUMMARIZATION_DEFAULT_MODELS[summ_provider]
        ),
    )

    prev_graph = prefill.get("graphrag") if isinstance(prefill, dict) else None
    if isinstance(prev_graph, dict):
        if not prev_graph.get("enabled"):
            prev_graph_mode = "1"
        elif prev_graph.get("doc_extractor") == "langextract":
            prev_graph_mode = "2"
        else:
            prev_graph_mode = "3"
    else:
        prev_graph_mode = "3"
    graphrag_mode: str = click.prompt(
        "\nGraphRAG (relationship-aware search across code + docs)\n"
        "1) Off — vector + keyword search only; no graph\n"
        "2) On, code + docs — graph from code structure AND document text\n"
        "     (uses your summarization model on docs)\n"
        "3) On, code only — graph from code structure; no extra model usage\n"
        "Select",
        type=click.Choice(["1", "2", "3"]),
        default=prev_graph_mode,
    )

    compute_on = click.confirm(
        "\nEnable compute query mode? (aggregates typed numeric records from sessions)",
        default=bool(_prev("compute.enabled", True)),
    )
    record_extraction_on = click.confirm(
        "\nExtract numeric records from sessions at ingest? (needed for compute mode)",
        default=bool(_prev("compute.record_extraction", True)),
    )
    compute_min_confidence = click.prompt(
        "\nMin record confidence summed by default compute (0.0–1.0)\n"
        "  Lower = include less-certain records; 0.7 keeps only HIGH-confidence",
        type=click.FloatRange(0.0, 1.0),
        default=float(_prev("compute.min_confidence", 0.7)),
    )

    embed_sessions = click.confirm(
        "\nEmbed chat sessions for semantic recall? (goes through your embedding "
        "provider)\n  Independent of chat summarization.",
        default=bool(_prev("session_indexing.enabled", False)),
    )
    archive_sessions = click.confirm(
        "\nBack up chat sessions locally? (free; stored in .brainpalace/, never "
        "leaves this machine)\n  Full raw transcripts, including any secrets "
        "pasted into chat.",
        default=bool(_prev("session_indexing.archive.enabled", True)),
    )
    index_git = click.confirm(
        "\nIndex git commit history? (commits may contain secrets)",
        default=bool(_prev("git_indexing.enabled", False)),
    )
    git_depth = int(_prev("git_indexing.depth", 5000))
    if index_git:
        git_depth = click.prompt(
            "How many commits back to index? (0 = unlimited)",
            default=git_depth,
            type=int,
        )
    from brainpalace_cli import optional_deps

    rerank_on = click.confirm(
        "\nEnable two-stage reranking? (sharper result ordering)\n  "
        f"{optional_deps.REGISTRY['reranker-local'].download_note}\n  "
        "(Skip this and set reranker.provider=ollama later for a torch-free reranker.)",
        default=bool(_prev("reranker.enabled", False)),
    )

    use_lemma = click.confirm(
        "\nUse lemmatization for BM25 keyword search? (better recall for inflected "
        f"languages{_lemma_languages_hint()})\n  "
        f"{optional_deps.REGISTRY['lemma-hr'].download_note}",
        default=_prev("bm25.engine", "stem") == "lemma",
    )

    suggested_port = _find_available_api_port(8000, 8300)
    click.echo(f"\nDiscovered available API port in 8000-8300 range: {suggested_port}")

    prev_host = _prev("api.host", "127.0.0.1")
    deployment_mode: str = click.prompt(
        "\nDeployment mode\n"
        "1) Localhost only (127.0.0.1)\n"
        "2) Network accessible (0.0.0.0 or custom host)\n"
        "3) Custom port on localhost\n"
        "Select",
        type=click.Choice(["1", "2", "3"]),
        default="2" if prev_host not in ("127.0.0.1", "") else "1",
    )

    api_host = "127.0.0.1"
    if deployment_mode == "2":
        host_mode: str = click.prompt(
            "\nHost selection\n" "1) 0.0.0.0\n" "2) Custom host/IP",
            type=click.Choice(["1", "2"]),
            default="2" if prev_host not in ("0.0.0.0", "127.0.0.1", "") else "1",
        )
        if host_mode == "1":
            api_host = "0.0.0.0"
        else:
            api_host = click.prompt("\nCustom host", default=prev_host or "0.0.0.0")

    api_port: int = click.prompt(
        "\nAPI port",
        type=click.IntRange(min=1, max=65535),
        default=int(_prev("api.port", suggested_port)),
    )

    # Dashboard (control-plane) settings are global — they govern the dashboard
    # process itself, not a single project — so only ask + write them for the
    # global config. The /dashboard/settings tab edits the same `dashboard:`
    # block later.
    dashboard_autostart = True
    dashboard_port = 8787
    if global_:
        dashboard_autostart = click.confirm(
            "\nAuto-start the web dashboard when you run 'brainpalace start'?",
            default=bool(_prev("dashboard.autostart", True)),
        )
        dashboard_port = click.prompt(
            "Dashboard port",
            type=click.IntRange(min=1, max=65535),
            default=int(_prev("dashboard.port", 8787)),
        )

    config: dict[str, Any] = {
        "embedding": {
            "provider": embed_provider,
            "model": embed_model,
        },
        "summarization": {
            "provider": summ_provider,
            "model": summ_model,
        },
        "graphrag": {
            "enabled": False,
        },
        "compute": {
            "enabled": compute_on,
            "record_extraction": record_extraction_on,
            "min_confidence": compute_min_confidence,
        },
        "session_indexing": {
            "enabled": embed_sessions,
            "archive": {"enabled": archive_sessions},
        },
        "git_indexing": {
            "enabled": index_git,
            "depth": git_depth,
        },
        "reranker": {
            "enabled": rerank_on,
        },
        "bm25": {
            "engine": "lemma" if use_lemma else "stem",
        },
        "api": {
            "host": api_host,
            "port": api_port,
        },
    }
    if global_:
        config["dashboard"] = {
            "autostart": dashboard_autostart,
            "port": dashboard_port,
        }
    if use_lemma:
        optional_deps.ensure_extra("lemma-hr", assume_yes=True)
    # Enabling reranking with the default local provider needs the heavy
    # cross-encoder extra (PyTorch). Install it on opt-in; a torch-free ollama
    # provider can be configured later instead.
    if rerank_on:
        optional_deps.ensure_extra("reranker-local", assume_yes=True)

    if embed_provider == "ollama":
        config["embedding"]["params"] = {
            "batch_size": int(batch_size or "10"),
            "request_delay_ms": int(request_delay_ms or 0),
        }

    if graphrag_mode == "2":
        config["graphrag"] = {
            "enabled": True,
            "store_type": "sqlite",
            "use_code_metadata": True,
            "doc_extractor": "langextract",
        }
        from brainpalace_cli import optional_deps

        optional_deps.ensure_extra("graphrag", assume_yes=True)
    elif graphrag_mode == "3":
        config["graphrag"] = {
            "enabled": True,
            "store_type": "sqlite",
            "use_code_metadata": True,
        }

    if global_:
        config_path = get_xdg_config_dir() / "config.yaml"
    else:
        config_path = _resolve_wizard_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]Config written to {config_path}[/]")

    # Validate the written config and warn if issues found
    post_write_errors = validate_config_file(config_path)
    if post_write_errors:
        console.print(
            "\n[bold yellow]Warning:[/] The generated config has validation issues:\n"
        )
        console.print(format_validation_errors(post_write_errors))
        if not click.confirm("Continue with this config anyway?", default=False):
            console.print(
                "[red]Config wizard aborted." " Please fix the issues and try again.[/]"
            )
            sys.exit(1)


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

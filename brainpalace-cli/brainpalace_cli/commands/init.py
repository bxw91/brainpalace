"""Init command for initializing an BrainPalace project."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel

from brainpalace_cli.migration import migrate_state_dir
from brainpalace_cli.xdg_paths import get_xdg_config_dir, migrate_legacy_paths

console = Console()

# Default configuration values for config.json (project settings only)
# Provider settings (embedding/summarization) go in config.yaml
DEFAULT_CONFIG = {
    "bind_host": "127.0.0.1",
    "port_range_start": 8000,
    "port_range_end": 8100,
    "auto_port": True,
    "chunk_size": 512,
    "chunk_overlap": 50,
    # Directories to exclude from indexing (glob patterns)
    "exclude_patterns": [
        "**/node_modules/**",
        "**/__pycache__/**",
        "**/.venv/**",
        "**/venv/**",
        "**/.git/**",
        "**/dist/**",
        "**/build/**",
        "**/target/**",
    ],
}

STATE_DIR_NAME = ".brainpalace"

# Default config.yaml written by `brainpalace init` for new projects (Phase L).
# Graph indexing is enabled with the cheap AST-code-only path: no LLM cost on
# docs, no extra dependencies. Users can run `brainpalace config wizard` to
# override (e.g. switch to LangExtract on docs).
DEFAULT_PROVIDER_CONFIG = {
    "embedding": {
        "provider": "openai",
        "model": "text-embedding-3-large",
    },
    "summarization": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
    },
    "graphrag": {
        "enabled": True,
        "store_type": "simple",
        "use_code_metadata": True,
    },
    "storage": {
        "backend": "chroma",
    },
}


def write_default_provider_config(state_dir: Path, force: bool = False) -> bool:
    """Write a sane default config.yaml in the project state dir.

    Phase L: ensures new projects get code-graph indexing on by default
    without requiring the user to run `brainpalace config wizard`.

    Precedence:
    1. If a user-level config exists at XDG (~/.config/brainpalace/config.yaml),
       copy it — respects whichever embedding/summarization provider the
       user configured globally.
    2. Otherwise write the hardcoded DEFAULT_PROVIDER_CONFIG (OpenAI
       embedding + Anthropic summarization + graphrag code-only).

    Returns True if the file was written, False if it already existed.
    """
    config_path = state_dir / "config.yaml"
    if config_path.exists() and not force:
        return False
    state_dir.mkdir(parents=True, exist_ok=True)

    # Prefer the user's global XDG config if present.
    xdg_global = get_xdg_config_dir() / "config.yaml"
    if xdg_global.is_file():
        shutil.copy2(xdg_global, config_path)
        return True

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            DEFAULT_PROVIDER_CONFIG,
            f,
            default_flow_style=False,
            sort_keys=False,
        )
    return True


# Markers in a CLAUDE.md that indicate the directory is a mono-repo workspace
# root, NOT a project. `init` refuses to create .brainpalace/ at such a root
# unless --force-monorepo-root is passed.
MONOREPO_CLAUDE_MD_MARKERS = (
    "Do not treat the workspace root as a project",
    "organisational container only",
    "organizational container only",
    "mono-repo workspace",
)


def _looks_like_monorepo_root(project_root: Path) -> bool:
    """Detect a mono-repo workspace root by inspecting CLAUDE.md markers."""
    claude_md = project_root / "CLAUDE.md"
    if not claude_md.is_file():
        return False
    try:
        contents = claude_md.read_text(errors="replace")
    except OSError:
        return False
    return any(marker in contents for marker in MONOREPO_CLAUDE_MD_MARKERS)


def _preflight_providers(state_dir: Path, json_output: bool) -> None:
    """Validate embedding/summarization providers before starting the server.

    Reuses the server's own validation rules (the CLI bundles the server) so
    there is one source of truth. On a critical error (e.g. a required API key
    is missing) prints the provider, the missing env var, and exits non-zero
    *before* any server start or index job — preventing the mid-init crash
    class. Non-critical warnings are surfaced but do not block.
    """
    import os

    try:
        from brainpalace_server.config.provider_config import (
            clear_settings_cache,
            has_critical_errors,
            load_provider_settings,
            validate_provider_config,
        )
    except Exception:  # noqa: BLE001 — server not importable: skip preflight
        return

    # Point validation at the project config.yaml we just wrote.
    prev = os.environ.get("BRAINPALACE_CONFIG")
    os.environ["BRAINPALACE_CONFIG"] = str(state_dir / "config.yaml")
    try:
        clear_settings_cache()
        errors = validate_provider_config(load_provider_settings())
        critical = has_critical_errors(errors)
    except Exception:  # noqa: BLE001 — never block init on the check itself
        return
    finally:
        if prev is None:
            os.environ.pop("BRAINPALACE_CONFIG", None)
        else:
            os.environ["BRAINPALACE_CONFIG"] = prev
        clear_settings_cache()

    if not critical:
        return

    messages = [str(e) for e in errors]
    if json_output:
        click.echo(
            json.dumps(
                {
                    "error": "provider_preflight_failed",
                    "messages": messages,
                    "state_dir": str(state_dir),
                }
            )
        )
    else:
        console.print("[red]Provider configuration error — not starting the server:[/]")
        for msg in messages:
            console.print(f"  {msg}")
        console.print(
            "\n[dim]Fix the configuration (set the missing API key env var or "
            "edit .brainpalace/config.yaml), then re-run.[/]"
        )
    raise SystemExit(1)


def enable_session_indexing(state_dir: Path) -> None:
    """Set ``session_indexing.enabled: true`` in the project config.yaml.

    Deep-merges into the existing config.yaml so the provider/graphrag/storage
    blocks written by ``write_default_provider_config`` are preserved. Privacy
    note: this opts the project into indexing AI chat transcripts; only called
    when the user explicitly opts in. The server reads this block at startup
    (``load_session_indexing_config``) to start the session watcher.
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    block = data.get("session_indexing")
    if not isinstance(block, dict):
        block = {}
    block["enabled"] = True
    data["session_indexing"] = block
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def ensure_gitignore_entry(project_root: Path, entry: str = ".brainpalace/") -> bool:
    """Append ``entry`` to the project's .gitignore if not already present.

    Idempotent: a line matching ``entry`` with or without a trailing slash
    counts as already present. Creates .gitignore if it does not exist.

    Args:
        project_root: Directory that holds (or will hold) .gitignore.
        entry: The line to ensure is present (default: ``.brainpalace/``).

    Returns:
        True if the entry was appended, False if it was already present.
    """
    gitignore = project_root / ".gitignore"
    if gitignore.exists():
        text = gitignore.read_text()
        lines = text.splitlines()
        if entry in lines or entry.rstrip("/") in lines:
            return False
        sep = "" if text == "" or text.endswith("\n") else "\n"
        with gitignore.open("a") as f:
            f.write(f"{sep}{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")
    return True


def _run_subcommand(
    cmd: list[str],
    *,
    step: str,
    json_output: bool,
) -> dict[str, object]:
    """Run a downstream `brainpalace` subcommand and capture the result.

    Returns a dict suitable for inclusion in the init JSON payload. Output is
    captured (never relayed to stdout/stderr automatically) to keep init's
    own banner clean; failures surface the captured stderr.
    """
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        if not json_output:
            console.print(f"[red]Post-init step '{step}' failed:[/] {exc}")
        return {
            "step": step,
            "status": "error",
            "error": str(exc),
            "command": cmd,
        }

    if completed.returncode != 0:
        if not json_output:
            console.print(
                f"[red]Post-init step '{step}' failed (exit {completed.returncode}):[/]"
            )
            if completed.stderr:
                console.print(completed.stderr.rstrip())
        return {
            "step": step,
            "status": "error",
            "exit_code": completed.returncode,
            "stderr": completed.stderr,
            "stdout": completed.stdout,
            "command": cmd,
        }

    return {
        "step": step,
        "status": "ok",
        "exit_code": 0,
        "stdout": completed.stdout,
        "command": cmd,
    }


def _emit_init_result(
    *,
    project_root: Path,
    resolved_state_dir: Path,
    config_path: Path,
    config: dict[str, object],
    gitignore_added: bool,
    post_init_steps: list[dict[str, object]],
    start_used: bool,
    watch: str,
    json_output: bool,
) -> None:
    """Print the init result, including any post-init step outcomes."""
    if json_output:
        click.echo(
            json.dumps(
                {
                    "status": "initialized",
                    "project_root": str(project_root),
                    "state_dir": str(resolved_state_dir),
                    "config_path": str(config_path),
                    "gitignore_updated": gitignore_added,
                    "config": config,
                    "post_init_steps": post_init_steps,
                },
                indent=2,
            )
        )
        return

    console.print(
        Panel(
            f"[green]Project initialized successfully![/]\n\n"
            f"[bold]Project Root:[/] {project_root}\n"
            f"[bold]State Directory:[/] {resolved_state_dir}\n"
            f"[bold]Configuration:[/] {config_path}",
            title="BrainPalace Initialized",
            border_style="green",
        )
    )

    started_ok = any(
        s.get("step") == "start" and s.get("status") == "ok" for s in post_init_steps
    )
    watched_ok = any(
        s.get("step") == "watch" and s.get("status") == "ok" for s in post_init_steps
    )

    console.print("\n[dim]Next steps:[/]")
    step_num = 1
    if not start_used:
        console.print(
            f"  {step_num}. Run [bold]brainpalace start[/] to start the server"
        )
        step_num += 1
    elif started_ok:
        console.print(f"  {step_num}. [green]Server started.[/]")
        step_num += 1

    if watch == "off":
        console.print(
            f"  {step_num}. Run [bold]brainpalace folders add <path>[/] "
            f"to index a folder"
        )
    elif watched_ok:
        console.print(
            f"  {step_num}. [green]Folder watched + initial indexing enqueued:[/] "
            f"{project_root}"
        )


def _start_and_watch(
    *,
    project_root: Path,
    resolved_state_dir: Path,
    config_path: Path,
    config: dict[str, object],
    gitignore_added: bool,
    watch: str,
    json_output: bool,
) -> list[dict[str, object]]:
    """Run the --start pipeline: provider preflight, server start, optional watch.

    Shared by a fresh init and a re-run on an already-initialized project, so
    `init --start` is idempotent (a first run that aborted at preflight can be
    re-run to actually start). Emits the failure result and exits non-zero on
    any failing step; returns the collected post-init steps on success.
    """
    post_init_steps: list[dict[str, object]] = []

    # Provider pre-flight: fail fast with an actionable message before
    # launching the server / queueing any index, so a misconfigured provider
    # (e.g. summarization=anthropic with no key) can't crash the server.
    _preflight_providers(resolved_state_dir, json_output)

    start_result = _run_subcommand(
        ["brainpalace", "start", "--path", str(project_root), "--json"],
        step="start",
        json_output=json_output,
    )
    post_init_steps.append(start_result)
    if start_result["status"] != "ok":
        _emit_init_result(
            project_root=project_root,
            resolved_state_dir=resolved_state_dir,
            config_path=config_path,
            config=config,
            gitignore_added=gitignore_added,
            post_init_steps=post_init_steps,
            start_used=True,
            watch=watch,
            json_output=json_output,
        )
        raise SystemExit(1)

    if watch != "off":
        watch_result = _run_subcommand(
            [
                "brainpalace",
                "folders",
                "add",
                str(project_root),
                "--watch",
                watch,
                "--include-code",
            ],
            step="watch",
            json_output=json_output,
        )
        post_init_steps.append(watch_result)
        if watch_result["status"] != "ok":
            _emit_init_result(
                project_root=project_root,
                resolved_state_dir=resolved_state_dir,
                config_path=config_path,
                config=config,
                gitignore_added=gitignore_added,
                post_init_steps=post_init_steps,
                start_used=True,
                watch=watch,
                json_output=json_output,
            )
            raise SystemExit(1)

    return post_init_steps


@click.command("init")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help="Project path (default: auto-detect project root)",
)
@click.option(
    "--host",
    default=DEFAULT_CONFIG["bind_host"],
    help=f"Server bind host (default: {DEFAULT_CONFIG['bind_host']})",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="Preferred server port (default: auto-select from range)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing configuration",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--state-dir",
    "-s",
    type=click.Path(file_okay=False, resolve_path=True),
    help="Custom state directory for index data (default: .brainpalace)",
)
@click.option(
    "--force-monorepo-root",
    is_flag=True,
    help=(
        "Allow init at a directory whose CLAUDE.md flags it as a mono-repo "
        "workspace root. Use only if you really want a project-level state "
        "dir at the workspace root."
    ),
)
@click.option(
    "--start",
    is_flag=True,
    help="Start the server after initialization (one-shot setup)",
)
@click.option(
    "--watch",
    type=click.Choice(["off", "auto"], case_sensitive=False),
    default="off",
    show_default=True,
    help=(
        "When combined with --start, register + index project_root with the "
        "given watch mode (default 'off' = no folder registration)."
    ),
)
@click.option(
    "--sessions/--no-sessions",
    "enable_sessions",
    default=None,
    help=(
        "Index this project's AI chat transcripts into searchable session "
        "memory (assistant + tool turns). ON by default for new projects: "
        "interactive runs confirm (default yes), non-interactive runs enable "
        "it. Pass --no-sessions to opt out."
    ),
)
def init_command(
    path: str | None,
    host: str,
    port: int | None,
    force: bool,
    json_output: bool,
    state_dir: str | None,
    force_monorepo_root: bool,
    start: bool,
    watch: str,
    enable_sessions: bool | None,
) -> None:
    """Initialize a new BrainPalace project.

    Creates the .brainpalace/ directory structure and writes
    a default config.json file.

    \b
    Examples:
      brainpalace init                              # Initialize in current project
      brainpalace init --path /my/project           # Initialize specific project
      brainpalace init --port 8080                  # Set preferred port
      brainpalace init --state-dir /custom/path     # Custom storage location
      brainpalace init --force                      # Overwrite existing config
      brainpalace init --start                      # Init then start the server
      brainpalace init --start --watch auto         # One-shot init + start + watch
    """
    try:
        # Trigger one-time migration from legacy ~/.brainpalace to XDG dirs
        migrate_legacy_paths()

        # Resolve project root — CWD when --path is omitted (B5).
        if path:
            project_root = Path(path).resolve()
        else:
            project_root = Path.cwd().resolve()

        # Defensive: refuse to create .brainpalace/ at a mono-repo workspace
        # root unless explicitly overridden.
        if not force_monorepo_root and _looks_like_monorepo_root(project_root):
            msg = (
                f"Refusing to init at mono-repo workspace root: {project_root}\n"
                "Its CLAUDE.md marks it as an organisational container, not a "
                "project.\n"
                "Recommended: `cd projects/<name> && brainpalace init`.\n"
                "Override with --force-monorepo-root if you really want a "
                "state dir here."
            )
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "error": "monorepo_root_refused",
                            "project_root": str(project_root),
                            "hint": (
                                "cd into a project subdir, or pass "
                                "--force-monorepo-root"
                            ),
                        }
                    )
                )
            else:
                console.print(f"[red]Error:[/] {msg}")
            raise SystemExit(1)

        # Use custom state_dir if provided, otherwise default
        if state_dir:
            resolved_state_dir = Path(state_dir).resolve()
        else:
            # Auto-migrate from legacy .claude/brainpalace if needed
            resolved_state_dir = migrate_state_dir(project_root)
        config_path = resolved_state_dir / "config.json"

        # Idempotent: re-running init on an initialized project is a no-op (B5),
        # EXCEPT when --start is passed — then skip the config write but still
        # run the start/watch pipeline so a first run that aborted at the
        # provider preflight can be resumed without --force.
        if config_path.exists() and not force:
            if start:
                try:
                    existing_config = json.loads(config_path.read_text())
                except (OSError, json.JSONDecodeError):
                    existing_config = {}
                if enable_sessions:
                    enable_session_indexing(resolved_state_dir)
                post_init_steps: list[dict[str, object]] = _start_and_watch(
                    project_root=project_root,
                    resolved_state_dir=resolved_state_dir,
                    config_path=config_path,
                    config=existing_config,
                    gitignore_added=False,
                    watch=watch,
                    json_output=json_output,
                )
                _emit_init_result(
                    project_root=project_root,
                    resolved_state_dir=resolved_state_dir,
                    config_path=config_path,
                    config=existing_config,
                    gitignore_added=False,
                    post_init_steps=post_init_steps,
                    start_used=True,
                    watch=watch,
                    json_output=json_output,
                )
                return
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "status": "already_initialized",
                            "project_root": str(project_root),
                            "state_dir": str(resolved_state_dir),
                            "config_path": str(config_path),
                        },
                        indent=2,
                    )
                )
            else:
                console.print(f"[green]Already initialized:[/] {config_path}")
                console.print(
                    "[dim]Use --force to overwrite the existing configuration.[/]"
                )
            return

        # Create state directory structure
        resolved_state_dir.mkdir(parents=True, exist_ok=True)
        (resolved_state_dir / "data").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "chroma_db").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "bm25_index").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "llamaindex").mkdir(exist_ok=True)
        (resolved_state_dir / "logs").mkdir(exist_ok=True)

        # Build configuration
        config = {
            **DEFAULT_CONFIG,
            "bind_host": host,
            "project_root": str(project_root),
        }
        if port is not None:
            config["port"] = port
            config["auto_port"] = False

        # Write configuration
        config_path.write_text(json.dumps(config, indent=2))

        # Phase L: write a default config.yaml (provider settings) with
        # graphrag.enabled=true so new projects get code-graph indexing
        # without needing `brainpalace config wizard`. Idempotent: skip
        # if config.yaml already exists. NOTE: never pass force here — a
        # re-init with --force overwrites the server config.json but must
        # preserve the user's provider/embedding/summarization/storage/
        # graphrag edits in config.yaml (use `brainpalace config` to change
        # providers). Clobbering them on --force was a data-loss papercut.
        provider_config_written = write_default_provider_config(
            resolved_state_dir, force=False
        )
        if force and not provider_config_written and not json_output:
            console.print(
                "[dim]Preserved existing .brainpalace/config.yaml provider "
                "settings (use `brainpalace config` to change providers).[/]"
            )

        # Session memory is ON by default for new projects: it indexes this
        # project's AI chat transcripts (assistant + tool turns). An interactive
        # TTY gets a confirmation defaulting to yes; non-interactive/--json runs
        # initialize it enabled. Explicit --no-sessions opts out. User turns
        # remain separately opt-in.
        #
        # The default-on only applies when we just wrote a fresh config.yaml
        # (i.e. a genuinely new project). On a re-init over an existing
        # config.yaml we leave it untouched so user edits are preserved — only
        # an explicit --sessions injects the block in that case.
        if enable_sessions is None:
            if not provider_config_written:
                enable_sessions = False
            elif not json_output and sys.stdin.isatty():
                enable_sessions = click.confirm(
                    "Enable session memory? It indexes this project's AI chat "
                    "transcripts (assistant + tool turns) for later recall.",
                    default=True,
                )
            else:
                enable_sessions = True
        if enable_sessions:
            enable_session_indexing(resolved_state_dir)

        # B5: ensure .brainpalace/ is git-ignored for the project.
        gitignore_added = ensure_gitignore_entry(project_root)

        post_init_steps = []

        if start:
            post_init_steps = _start_and_watch(
                project_root=project_root,
                resolved_state_dir=resolved_state_dir,
                config_path=config_path,
                config=config,
                gitignore_added=gitignore_added,
                watch=watch,
                json_output=json_output,
            )

        _emit_init_result(
            project_root=project_root,
            resolved_state_dir=resolved_state_dir,
            config_path=config_path,
            config=config,
            gitignore_added=gitignore_added,
            post_init_steps=post_init_steps,
            start_used=start,
            watch=watch,
            json_output=json_output,
        )

    except PermissionError as e:
        if json_output:
            click.echo(json.dumps({"error": f"Permission denied: {e}"}))
        else:
            console.print(f"[red]Permission Error:[/] {e}")
        raise SystemExit(1) from e
    except OSError as e:
        if json_output:
            click.echo(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error:[/] {e}")
        raise SystemExit(1) from e

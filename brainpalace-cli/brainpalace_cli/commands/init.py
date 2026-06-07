"""Init command for initializing an BrainPalace project."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel

from brainpalace_cli.commands.init_plan import (
    downgrade_to_config_only,
    format_init_plan,
    resolve_init_plan,
)
from brainpalace_cli.commands.plugin_detect import claude_plugin_installed
from brainpalace_cli.commands.session_hooks import (
    install_session_hooks,
    prune_extraction_hooks,
)
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


def _stdin_is_tty() -> bool:
    """Whether stdin is an interactive terminal (seam for tests; CliRunner swaps
    ``sys.stdin``, so this is monkeypatched rather than ``sys.stdin.isatty``)."""
    return sys.stdin.isatty()


# Embedding providers in preference order: (provider, model, api-key env var).
# None env var = no key needed (local). `init` picks the first whose key is
# present in the environment, so an OpenAI-only env doesn't force an edit.
_EMBEDDING_PREFERENCE = [
    ("openai", "text-embedding-3-large", "OPENAI_API_KEY"),
    ("cohere", "embed-english-v3.0", "COHERE_API_KEY"),
]
_EMBEDDING_FALLBACK = {"provider": "openai", "model": "text-embedding-3-large"}

# Summarization providers in preference order: (provider, model, api-key env var).
_SUMMARIZATION_PREFERENCE = [
    ("anthropic", "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY"),
    ("openai", "gpt-5-mini", "OPENAI_API_KEY"),
    ("gemini", "gemini-3.1-flash-lite", "GEMINI_API_KEY"),
    ("grok", "grok-4-fast", "XAI_API_KEY"),
]
_SUMMARIZATION_FALLBACK = {
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
}


def _pick_provider(
    preference: list[tuple[str, str, str]],
    fallback: dict[str, str],
) -> dict[str, str]:
    """Pick the first provider whose API-key env var is set, else the fallback.

    Gives a zero-edit happy path: when only one provider key is present in the
    environment, both embedding and summarization default to a provider that
    key can actually drive — instead of hardcoding anthropic + openai and
    forcing the user to edit config.yaml on a fresh project (Bug 0).
    """
    for provider, model, env_var in preference:
        if os.environ.get(env_var):
            return {"provider": provider, "model": model}
    return dict(fallback)


def build_default_provider_config(
    bm25_language: str = "en",
    bm25_engine: str = "stem",
    reranking: bool = True,
) -> dict[str, object]:
    """Build the default config.yaml provider block from detected env keys.

    Graph indexing is enabled with the cheap AST-code-only path: no LLM cost on
    docs, no extra dependencies. The store defaults to ``sqlite`` (persistent,
    incrementally-writable, temporal-validity) rather than the in-memory
    ``simple`` store. Users can run `brainpalace config wizard` to override
    (e.g. switch to LangExtract on docs).
    """
    return {
        "embedding": _pick_provider(_EMBEDDING_PREFERENCE, _EMBEDDING_FALLBACK),
        "summarization": _pick_provider(
            _SUMMARIZATION_PREFERENCE, _SUMMARIZATION_FALLBACK
        ),
        "reranker": {
            # Two-stage reranking is ON by default (local cross-encoder; adds
            # query latency, no API/token cost). Disable with --no-reranking.
            "enabled": reranking,
        },
        "graphrag": {
            "enabled": True,
            "store_type": "sqlite",
            "use_code_metadata": True,
        },
        "storage": {
            "backend": "chroma",
        },
        "bm25": {
            "language": bm25_language,
            "engine": bm25_engine,
        },
    }


def _preview_embedding(project_root: Path) -> tuple[str, str]:
    """Resolve the embedding ``(provider, model)`` the init will actually use.

    Precedence mirrors the config write: existing project
    ``.brainpalace/config.yaml`` → XDG global → env-detected default
    (:func:`build_default_provider_config`). Used only to name the real provider
    in the init preview."""
    for cfg in (
        project_root / STATE_DIR_NAME / "config.yaml",
        get_xdg_config_dir() / "config.yaml",
    ):
        try:
            data = yaml.safe_load(cfg.read_text()) or {}
        except (OSError, ValueError):
            continue
        emb = data.get("embedding") if isinstance(data, dict) else None
        if isinstance(emb, dict) and emb.get("provider") and emb.get("model"):
            return str(emb["provider"]), str(emb["model"])
    emb_default = build_default_provider_config()["embedding"]
    return str(emb_default["provider"]), str(emb_default["model"])  # type: ignore[index]


def _write_reranker_config(state_dir: Path, enabled: bool) -> None:
    """Idempotently set ``reranker.enabled`` in the project config.yaml.

    Preserves all other keys; the server's ``load_provider_settings()`` reads
    ``reranker.enabled`` at startup (env ``ENABLE_RERANKING`` still overrides).
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
        except (OSError, ValueError):
            data = {}
    block = data.get("reranker")
    if not isinstance(block, dict):
        block = {}
    block["enabled"] = enabled
    data["reranker"] = block
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def write_default_provider_config(
    state_dir: Path,
    force: bool = False,
    bm25_language: str = "en",
    bm25_engine: str = "stem",
    reranking: bool = True,
) -> bool:
    """Write a sane default config.yaml in the project state dir.

    Phase L: ensures new projects get code-graph indexing on by default
    without requiring the user to run `brainpalace config wizard`.

    Precedence:
    1. If a user-level config exists at XDG (~/.config/brainpalace/config.yaml),
       copy it — respects whichever embedding/summarization provider the
       user configured globally. The bm25 block is then merged/overwritten
       with the explicitly passed language/engine values.
    2. Otherwise write a default provider block chosen from detected env keys
       (see build_default_provider_config) + graphrag code-only.

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
        # Merge bm25 + reranker blocks on top of the XDG copy.
        _write_bm25_config(state_dir, bm25_language, bm25_engine)
        _write_reranker_config(state_dir, reranking)
        return True

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            build_default_provider_config(
                bm25_language=bm25_language,
                bm25_engine=bm25_engine,
                reranking=reranking,
            ),
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


def _write_bm25_config(
    state_dir: Path,
    language: str,
    engine: str,
) -> None:
    """Deep-merge bm25.{language,engine} into the project config.yaml.

    Delegates to :func:`brainpalace_cli.commands.bm25_project.set_project_bm25`.
    Idempotent: preserves all existing keys and only sets the bm25 block.
    The server's ``load_bm25_config()`` reads this block at startup.
    """
    from brainpalace_cli.commands.bm25_project import set_project_bm25

    set_project_bm25(state_dir, language=language, engine=engine)


def _check_simplemma_importable() -> bool:
    """Return True if simplemma can be imported (lemma engine is available)."""
    try:
        import importlib

        importlib.import_module("simplemma")
        return True
    except ImportError:
        return False


def _preflight_lemma(engine: str, json_output: bool) -> None:
    """Fail fast when engine=lemma but simplemma is not installed.

    Mirrors the style of _preflight_providers: prints an actionable message
    (the exact pip install command) and exits non-zero BEFORE the server
    starts, so the user gets clear guidance instead of a cryptic mid-index
    crash.
    """
    if engine != "lemma":
        return
    if _check_simplemma_importable():
        return

    install_hint = "pip install 'brainpalace[lemma-hr]'"
    if json_output:
        import json as _json

        click.echo(
            _json.dumps(
                {
                    "error": "lemma_preflight_failed",
                    "message": (
                        "simplemma is required for engine=lemma but is not installed."
                    ),
                    "install": install_hint,
                }
            )
        )
    else:
        console.print(
            "[red]BM25 lemma engine requires simplemma — not installed:[/]\n"
            f"  {install_hint}\n"
            "[dim]Re-run after installing, or switch to --bm25-engine stem.[/]"
        )
    raise SystemExit(1)


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


def _existing_session_keys(state_dir: Path) -> set[str]:
    """Keys present in any existing ``session_indexing`` block in config.yaml.

    Used to detect an XDG-inherited block so ``init`` respects the global
    default instead of clobbering it. Returns an empty set when no block exists.
    """
    config_path = state_dir / "config.yaml"
    if not config_path.exists():
        return set()
    try:
        loaded = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return set()
    block = loaded.get("session_indexing") if isinstance(loaded, dict) else None
    return set(block.keys()) if isinstance(block, dict) else set()


def write_session_config(
    state_dir: Path,
    index: bool | None = None,
    archive: bool | None = None,
    extract_mode: str | None = None,
) -> None:
    """Write the session capabilities + extraction engine into config.yaml.

    Deep-merges into the existing config.yaml so the provider/graphrag/storage
    blocks written by ``write_default_provider_config`` (and any XDG-inherited
    ``session_indexing`` keys) are preserved. Only the explicitly-passed
    capabilities are set (``None`` leaves the existing value untouched), so a
    re-init that toggles one capability never clobbers the other. ``index``
    embeds transcripts (billable opt-in); ``archive`` copies raw transcripts
    (durable backup, no embeddings); ``extract_mode`` selects the distillation
    engine (``subagent`` | ``provider`` | ``off``) under ``session_extraction:``.
    The server reads these blocks at startup (``load_session_indexing_config`` /
    ``load_session_extraction_config``).
    """
    if index is None and archive is None and extract_mode is None:
        return
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    if index is not None or archive is not None:
        block = data.get("session_indexing")
        if not isinstance(block, dict):
            block = {}
        if index is not None:
            block["enabled"] = bool(index)
        if archive is not None:
            archive_block = block.get("archive")
            if not isinstance(archive_block, dict):
                archive_block = {}
            archive_block["enabled"] = bool(archive)
            block["archive"] = archive_block
        data["session_indexing"] = block
    if extract_mode is not None:
        extract_block = data.get("session_extraction")
        if not isinstance(extract_block, dict):
            extract_block = {}
        extract_block["mode"] = extract_mode
        data["session_extraction"] = extract_block
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def write_git_config(
    state_dir: Path, enabled: bool | None = None, depth: int | None = None
) -> None:
    """Deep-merge the ``git_indexing`` opt-in into config.yaml.

    ``enabled=None`` leaves the existing block untouched (no-op), so a re-init
    that doesn't ask the question never clobbers a prior choice. ``depth=None``
    leaves the depth at the server default (``0`` = index the entire history);
    pass a value to cap the first full pass. Preserves the
    provider/graphrag/session blocks already written. Git-history indexing is
    privacy-first (commits can carry secrets), hence written only when chosen.
    """
    if enabled is None:
        return
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    block = data.get("git_indexing")
    if not isinstance(block, dict):
        block = {}
    block["enabled"] = bool(enabled)
    if depth is not None:
        block["depth"] = int(depth)
    data["git_indexing"] = block
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def read_graphrag_store_type(state_dir: Path) -> str | None:
    """Return the project's configured ``graphrag.store_type``, or None.

    None when there is no config.yaml, no ``graphrag`` block, or no explicit
    ``store_type`` (in which case the server's default — now ``sqlite`` — applies
    and there is nothing to migrate).
    """
    config_path = state_dir / "config.yaml"
    if not config_path.exists():
        return None
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return None
    block = data.get("graphrag") if isinstance(data, dict) else None
    if isinstance(block, dict) and block.get("store_type") is not None:
        return str(block["store_type"])
    return None


def read_session_state(state_dir: Path) -> tuple[str, bool]:
    """Return ``(session_extraction.mode, session_indexing.enabled)`` from config.yaml.

    Session capabilities live in ``config.yaml`` (not ``config.json``), so the
    re-init result banner must read them here to report the true state. Defaults
    to ``("off", False)`` when absent/unreadable.
    """
    config_path = state_dir / "config.yaml"
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return ("off", False)
    if not isinstance(data, dict):
        return ("off", False)
    extract = data.get("session_extraction")
    mode = extract.get("mode", "off") if isinstance(extract, dict) else "off"
    index = data.get("session_indexing")
    enabled = bool(index.get("enabled", False)) if isinstance(index, dict) else False
    return (str(mode), enabled)


def migrate_graph_store_to_sqlite(state_dir: Path) -> bool:
    """Flip an existing ``graphrag.store_type: simple`` to ``sqlite`` in place.

    A one-time, in-place config upgrade so an already-indexed project gains the
    persistent + temporal SQLite graph store. Only changes the value when it is
    currently ``simple``; every other config key is preserved. Returns True if a
    change was written, False otherwise (already sqlite / absent / unreadable) —
    so it is idempotent. The server replays the existing ``simple`` JSON graph
    into SQLite on next boot (JSON kept for rollback); no re-indexing is needed.
    """
    config_path = state_dir / "config.yaml"
    if not config_path.exists():
        return False
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    block = data.get("graphrag")
    if not isinstance(block, dict) or block.get("store_type") != "simple":
        return False
    block["store_type"] = "sqlite"
    data["graphrag"] = block
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    return True


def _prune_old_extraction_hooks(home: Path) -> None:
    """Remove any old CLI-installed extraction hooks from ``settings.json``.

    They are now owned by the Claude Code plugin; leaving them would double-run
    with the plugin's SessionEnd/UserPromptSubmit. No-op when settings.json is
    absent or unparseable. Used on the plugin-present path (where we must NOT
    install the reminder either, to avoid a double SessionStart).
    """
    settings_path = home / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    settings_path.write_text(
        json.dumps(prune_extraction_hooks(data), indent=2) + "\n", encoding="utf-8"
    )


def apply_extract_engine(
    state_dir: Path,
    project_root: Path,
    enabled: bool,
    home: Path | None = None,
) -> str:
    """Persist the session-summarization mode + reconcile Claude Code hooks.

    ``enabled`` is the resolved ``plan.extract``. When off → write
    ``session_extraction.mode: off``; when on → write ``subagent``: summarization
    happens ONLY inside Claude Code (the plugin, free on your subscription). The
    server never falls back to a paid provider on its own. (The ``provider`` and
    ``auto`` engines remain available, but only as an explicit config opt-in.)

    Hook reconciliation follows the same plugin-presence rule:
    - **Plugin present** → the plugin owns all 3 hooks (SessionStart reminder +
      both extraction hooks). We only prune any old CLI-installed extraction
      hooks, and do NOT install the reminder (avoids a double SessionStart).
    - **Plugin absent** (CLI/MCP only) → install the SessionStart reminder via
      :func:`install_session_hooks` (which also prunes old extraction hooks).

    Returns the resolved mode (``subagent`` | ``off``).
    """
    mode = "subagent" if enabled else "off"
    write_session_config(state_dir, extract_mode=mode)
    home = home or Path.home()
    if claude_plugin_installed(project=project_root):
        _prune_old_extraction_hooks(home)
    else:
        install_session_hooks(home)
    return mode


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


def _brainpalace_argv() -> list[str]:
    """Resolve how to invoke a nested ``brainpalace`` subcommand.

    Prefer the installed ``brainpalace`` console script on PATH. When it is not
    found (running from source, as a module, or an uninstalled dev checkout),
    fall back to ``python -m brainpalace_cli`` with the current interpreter so
    start/watch still work without a PATH binary.
    """
    exe = shutil.which("brainpalace")
    if exe:
        return [exe]
    return [sys.executable, "-m", "brainpalace_cli"]


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
    extract_on: bool = False,
    plugin_present: bool = False,
    sessions_on: bool = False,
    embedding: tuple[str, str] | None = None,
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

    # Separate what already happened (status) from what the user still has to
    # do (actionable). Reusing one "Next steps" header for both read as if the
    # status lines were chores the user must perform.
    done: list[str] = []
    todo: list[str] = []
    if not start_used:
        todo.append("Run [bold]brainpalace start[/] to start the server")
    elif started_ok:
        done.append("Server started.")
    if watch == "off":
        todo.append("Run [bold]brainpalace folders add <path>[/] to index a folder")
    elif watched_ok:
        done.append(f"Folder watched + initial indexing enqueued: {project_root}")

    # Surface the real (billable) session-embedding cost — it runs on the started
    # server via the embedding provider, independent of summarization.
    if sessions_on and start_used and embedding is not None:
        from brainpalace_cli.commands.init_plan import (
            _provider_label,
            _trim_model_id,
        )

        prov, model = embedding
        done.append(
            f"Chat-session embedding enqueued → "
            f"{_provider_label(prov)} {_trim_model_id(model)}"
        )

    if done:
        console.print("\n[dim]Done:[/]")
        for item in done:
            console.print(f"  [green]✓[/] {item}")

    # Chat summaries reflect the resolved engine + plugin presence: the subagent
    # path only runs when the Claude Code plugin is actually installed.
    if not extract_on:
        console.print("\n[dim]Chat summaries:[/] off.")
    elif plugin_present:
        console.print(
            "\n[dim]Chat summaries:[/] run on the free Claude Code Haiku subagent "
            "[bold]after your first prompt[/] — in batches of up to 8 sessions "
            "(≤1 MB) with a 5-minute cool-down between batches."
        )
    else:
        console.print(
            "\n[dim]Chat summaries:[/] configured (subagent) but the Claude Code "
            "plugin [bold]isn't installed[/], so sessions won't be summarized yet. "
            "Install it: [bold]brainpalace install-agent[/]"
        )

    console.print("\n[dim]Next steps:[/]")
    for item in todo:
        console.print(f"  • {item}")
    if started_ok and watched_ok:
        # Indexing runs in the background job worker — point the user at it.
        console.print(
            "  • Indexing runs in the background. Watch it: "
            "[bold]brainpalace status[/] (jobs: [bold]brainpalace jobs[/])"
        )
        console.print('  • Then query: [bold]brainpalace query "your question"[/]')
    elif not todo:
        console.print("  • Check health: [bold]brainpalace status[/]")


def _start_and_watch(
    *,
    project_root: Path,
    resolved_state_dir: Path,
    config_path: Path,
    config: dict[str, object],
    gitignore_added: bool,
    watch: str,
    json_output: bool,
    bm25_engine: str = "stem",
) -> list[dict[str, object]]:
    """Run the --start pipeline: provider preflight, server start, optional watch.

    Shared by a fresh init and a re-run on an already-initialized project, so
    `init --start` is idempotent (a first run that aborted at preflight can be
    re-run to actually start). Emits the failure result and exits non-zero on
    any failing step; returns the collected post-init steps on success.
    """
    post_init_steps: list[dict[str, object]] = []

    # Lemma pre-flight: engine=lemma requires simplemma; fail fast before server
    # start so the user gets a clear install hint instead of a mid-index crash.
    _preflight_lemma(bm25_engine, json_output)

    # Provider pre-flight: fail fast with an actionable message before
    # launching the server / queueing any index, so a misconfigured provider
    # (e.g. summarization=anthropic with no key) can't crash the server.
    _preflight_providers(resolved_state_dir, json_output)

    # The start subcommand polls the server's /health until it answers, so this
    # step blocks for the server's cold-boot (can be ~a minute on first launch).
    # Tell the user why nothing seems to be happening — the wait is server boot,
    # not transcript/document work (indexing is enqueued and runs in background).
    if not json_output:
        console.print("[dim]Starting server… (first boot can take up to a minute)[/]")
    start_result = _run_subcommand(
        [*_brainpalace_argv(), "start", "--path", str(project_root), "--json"],
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
        if not json_output:
            console.print("[dim]Registering folder + enqueuing initial indexing…[/]")
        watch_result = _run_subcommand(
            [
                *_brainpalace_argv(),
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
    "--start/--no-start",
    "start",
    default=None,
    help=(
        "Start the server after init. Default: ON in an interactive terminal "
        "(after a confirmation) or with --yes; OFF in non-interactive/--json "
        "runs. --no-start forces config-only."
    ),
)
@click.option(
    "--watch",
    type=click.Choice(["off", "auto"], case_sensitive=False),
    default=None,
    help=(
        "Folder watch mode when starting (auto = register + index project_root "
        "+ live re-index). Default 'auto' when starting, else 'off'."
    ),
)
@click.option(
    "--no-watch",
    "no_watch",
    is_flag=True,
    help="Do not register/watch the project folder (alias for --watch off).",
)
@click.option(
    "--yes",
    "-y",
    "yes",
    is_flag=True,
    help="Skip the confirmation prompt and apply the full resolved plan.",
)
@click.option(
    "--sessions/--no-sessions",
    "enable_sessions",
    default=None,
    help=(
        "INDEX this project's AI chat transcripts into searchable session "
        "memory (embeddings, billable). ON by default for new projects: "
        "interactive runs confirm (default yes), non-interactive runs enable "
        "it. Pass --no-sessions to opt out (archive still runs)."
    ),
)
@click.option(
    "--archive/--no-archive",
    "enable_archive",
    default=None,
    help=(
        "ARCHIVE raw transcripts under .brainpalace/ as a durable backup (no "
        "embeddings, independent of indexing). ON by default. Pass "
        "--no-archive to opt out."
    ),
)
@click.option(
    "--extract/--no-extract",
    "enable_extract",
    default=None,
    help=(
        "SUMMARIZE each session into durable knowledge (summary, decisions, "
        "triplets). ON by default, summarized ONLY inside Claude Code (the "
        "plugin, free on your Claude Code subscription — no separate API bill). "
        "The server does not summarize on its own. Pass --no-extract to opt out."
    ),
)
@click.option(
    "--git-history/--no-git-history",
    "enable_git_history",
    default=None,
    help=(
        "INDEX this repo's git commit history (message + diff stat) as "
        "searchable chunks. OFF by default — commits can contain secrets, so "
        "this is a deliberate opt-in. Interactive runs ask (default no)."
    ),
)
@click.option(
    "--migrate-graph-store/--no-migrate-graph-store",
    "enable_graph_migrate",
    default=None,
    help=(
        "On an already-initialized project whose graph store is the legacy "
        "in-memory 'simple' backend, upgrade graphrag.store_type to 'sqlite' "
        "(persistent + temporal; the existing graph is replayed into sqlite on "
        "next start, with the JSON kept for rollback). Interactive runs ask "
        "(default yes). No effect on fresh inits or projects already on sqlite."
    ),
)
@click.option(
    "--language",
    "bm25_language",
    default="en",
    show_default=True,
    help=(
        "Project default natural language for BM25 indexing (ISO 639-1, e.g. "
        "en, de, hr). Written to bm25.language in config.yaml."
    ),
)
@click.option(
    "--reranking/--no-reranking",
    "enable_reranking",
    default=None,
    help=(
        "Two-stage reranking: a local cross-encoder re-scores the top "
        "candidates for finer relevance ordering. ON by default (local; adds "
        "query latency, no API/token cost). Interactive runs confirm (default "
        "yes); writes reranker.enabled to config.yaml."
    ),
)
@click.option(
    "--bm25-engine",
    "bm25_engine",
    default="stem",
    show_default=True,
    type=click.Choice(["stem", "lemma"], case_sensitive=False),
    help=(
        "BM25 stemming engine: 'stem' (Snowball, no extra deps) or 'lemma' "
        "(simplemma, better recall for morphologically-rich languages). Written "
        "to bm25.engine in config.yaml. engine=lemma requires simplemma: "
        "pip install 'brainpalace[lemma-hr]'."
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
    start: bool | None,
    watch: str | None,
    no_watch: bool,
    yes: bool,
    enable_sessions: bool | None,
    enable_archive: bool | None,
    enable_extract: bool | None,
    enable_git_history: bool | None,
    enable_graph_migrate: bool | None,
    enable_reranking: bool | None,
    bm25_language: str,
    bm25_engine: str,
) -> None:
    """Initialize a new BrainPalace project.

    Creates the .brainpalace/ directory structure and writes
    a default config.json file.

    \b
    A bare `brainpalace init` writes config, starts the server, indexes the
    project (watch=auto), and backs up chat sessions locally (free). An
    interactive run then ASKS before the two session features: summarize chat
    sessions (free, Claude Code Haiku subagent) and embed chat sessions (billable
    — sends transcript content to your embedding provider). Embedding is OPT-IN:
    the default and --yes do NOT embed sessions; pass --sessions to enable it
    non-interactively. --json stays config-only unless --yes.

    \b
    Examples:
      brainpalace init                  # Interactive: asks about summarize/embed
      brainpalace init --yes            # Non-interactive: archive + summarize, no embed
      brainpalace init --sessions       # Also embed chat sessions (billable)
      brainpalace init --no-start       # Config only (no server, no indexing)
      brainpalace init --no-sessions    # Never embed chat sessions
      brainpalace init --no-watch       # Start, but do not index/watch the folder
      brainpalace init --path /my/proj  # Initialize a specific project
      brainpalace init --force          # Overwrite existing config
    """
    try:
        # Trigger one-time migration from legacy ~/.brainpalace to XDG dirs
        migrate_legacy_paths()

        # Resolve project root FIRST so the preview can name the real providers
        # and detect the plugin (subagent summarization needs it). CWD when
        # --path is omitted (B5).
        if path:
            project_root = Path(path).resolve()
        else:
            project_root = Path.cwd().resolve()

        # Resolve the action plan up front so both the already-initialized
        # branch and the fresh-init branch agree on what to do. Implicit
        # all-on defaults apply only with consent (TTY confirm or --yes);
        # --json forces non-interactive.
        is_tty = _stdin_is_tty() and not json_output
        plan = resolve_init_plan(
            start=start,
            watch=watch,
            no_watch=no_watch,
            sessions=enable_sessions,
            archive=enable_archive,
            extract=enable_extract,
            git_history=enable_git_history,
            yes=yes,
            is_tty=is_tty,
        )
        # Whether the user explicitly decided session embedding — via flag OR the
        # interactive prompt below. An explicit choice wins over an XDG-inherited
        # session_indexing block at write time.
        sessions_chosen = enable_sessions is not None

        # Defensive: refuse to create .brainpalace/ at a mono-repo workspace
        # root unless explicitly overridden. Done before any interactive prompt
        # so we never ask a series of questions and then refuse.
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

        # Resolve the state dir before the consent block so the graph-store
        # upgrade can be asked alongside the other questions and shown in the
        # "init will:" preview.
        if state_dir:
            resolved_state_dir = Path(state_dir).resolve()
        else:
            # Auto-migrate from legacy .claude/brainpalace if needed
            resolved_state_dir = migrate_state_dir(project_root)
        config_path = resolved_state_dir / "config.json"

        # A re-init of a project still on the legacy in-memory 'simple' graph
        # store is the only case where the one-time sqlite upgrade is offered.
        # sqlite is now the default (persistent + temporal); the server replays
        # the existing simple JSON graph into sqlite on next boot (JSON kept for
        # rollback). Decision: explicit flag wins; an interactive run asks below
        # (default yes); a non-interactive run upgrades only with the flag, or
        # with --yes opting into defaults.
        existing_simple_store = (
            config_path.exists()
            and not force
            and read_graphrag_store_type(resolved_state_dir) == "simple"
        )
        if not existing_simple_store:
            graph_migrate = False
        elif enable_graph_migrate is not None:
            graph_migrate = bool(enable_graph_migrate)
        else:
            graph_migrate = bool(yes)

        # Commit cap for git-history indexing. None ⇒ leave at the server
        # default (0 = entire history); an interactive opt-in may set a cap.
        git_depth: int | None = None

        # Reranking is ON by default; an explicit flag or interactive answer wins.
        reranking_final: bool = True if enable_reranking is None else enable_reranking

        if plan.confirm:
            embedding = _preview_embedding(project_root)
            plugin_present = claude_plugin_installed(project=project_root)

            # Granular consent — ask only what an explicit flag didn't already set.
            # Order: summarize first (free baseline recall), then embed (the paid
            # detail upgrade that references the summaries).
            extract_ans: bool = bool(plan.extract)
            if enable_extract is None:
                console.print(
                    "\n[bold]Summarize chat sessions?[/] "
                    "(distil past chats into summaries + a decisions digest)\n"
                    "  Free — runs on the Claude Code Haiku subagent (needs the "
                    "Claude Code plugin).\n"
                    "  Makes past chats searchable by topic. Reads full transcripts; "
                    "writes\n  BRAINPALACE_DECISIONS.md. Disable later: --no-extract."
                )
                extract_ans = click.confirm("Summarize chat sessions?", default=True)

            sessions_ans: bool = bool(plan.sessions)
            if enable_sessions is None:
                from brainpalace_cli.commands.init_plan import (
                    _provider_label,
                    _trim_model_id,
                )

                prov, model = embedding
                tag = f"{_provider_label(prov)} {_trim_model_id(model)}"
                console.print(
                    "\n[bold]Embed chat sessions too?[/] "
                    "(search the FULL verbatim text, not just summaries)\n"
                    "  Summaries above already make past chats searchable. Embedding "
                    "adds search over\n  the complete raw transcripts — good for exact "
                    f"code/commands — but sends that\n  content to {tag}. Cheap "
                    "(usually a few cents), but a large history\n  adds many tokens. "
                    "Enable later: --sessions."
                )
                sessions_ans = click.confirm("Embed chat sessions too?", default=False)
                sessions_chosen = True  # prompt answer is an explicit choice

            git_history_ans: bool = bool(plan.git_history)
            if enable_git_history is None:
                console.print(
                    "\n[bold]Index git commit history?[/] "
                    "(make past commits searchable: message + changed-file list)\n"
                    "  [yellow]Off by default[/] — commit diffs/messages can "
                    "contain secrets, so this is opt-in.\n"
                    "  Nothing is copied; chunks reference the commit sha. "
                    "Enable later: --git-history."
                )
                git_history_ans = click.confirm(
                    "Index git commit history?", default=False
                )
                if git_history_ans:
                    console.print(
                        "  How far back? Each commit is embedded, so a very large "
                        "history\n  costs more on the first pass. [dim]0 = "
                        "unlimited (entire history).[/]"
                    )
                    git_depth = click.prompt(
                        "How many commits back to index? (0 = unlimited)",
                        default=0,
                        type=int,
                    )

            # Graph-store upgrade — asked here (with the other questions) so it
            # appears in the "init will:" preview below and is gated by Proceed.
            if existing_simple_store and enable_graph_migrate is None:
                console.print(
                    "\n[bold]Upgrade graph store to sqlite?[/] "
                    "(this project uses the legacy in-memory 'simple' store)\n"
                    "  sqlite adds persistence + temporal validity (decision "
                    "history). Your existing\n  graph is migrated automatically "
                    "on next start; the JSON is kept for rollback."
                )
                graph_migrate = click.confirm(
                    "Upgrade graph store to sqlite?", default=True
                )

            # Rebuild the plan from the answers (bools ⇒ explicit, so they win).
            plan = resolve_init_plan(
                start=start,
                watch=watch,
                no_watch=no_watch,
                sessions=sessions_ans,
                archive=enable_archive,
                extract=extract_ans,
                git_history=git_history_ans,
                yes=yes,
                is_tty=is_tty,
            )
            summarize: tuple[str, ...] | None = (
                ("subagent",) if plan.extract and plugin_present else None
            )
            console.print(
                "\n"
                + format_init_plan(
                    plan,
                    embedding=embedding,
                    summarize=summarize,
                    graph_migrate=graph_migrate,
                )
            )
            if not click.confirm("Proceed?", default=True):
                plan = downgrade_to_config_only(plan)
                graph_migrate = False  # declining the plan cancels the upgrade too

        # Idempotent: re-running init on an initialized project is a no-op (B5),
        # EXCEPT when --start is passed — then skip the config write but still
        # run the start/watch pipeline so a first run that aborted at the
        # provider preflight can be resumed without --force. (The mono-repo
        # refusal + state_dir resolution + graph-store upgrade decision all ran
        # above, before the consent block.)
        if config_path.exists() and not force:
            # Apply the resolved one-time graph-store upgrade (decided above, and
            # asked in the consent block when interactive). The server replays
            # the existing simple JSON graph into sqlite on next boot (JSON kept
            # for rollback). Runs before the start/no-start split so a plain
            # re-init upgrades too.
            if graph_migrate and migrate_graph_store_to_sqlite(resolved_state_dir):
                if not json_output:
                    console.print(
                        "[dim]Graph store upgraded: simple → sqlite. The existing "
                        "graph migrates on next server start (JSON kept for "
                        "rollback).[/]"
                    )

            # Persist the git-history opt-in for an EXISTING project too. The
            # consent prompt / flag set plan.git_history above, but the fresh
            # write path below isn't taken on a re-init — without this the
            # answer was silently dropped. Explicit flag wins (can disable);
            # otherwise an interactive "yes" opts in. A bare re-init (no flag,
            # prompt declined/skipped) leaves any existing setting untouched.
            if enable_git_history is not None:
                write_git_config(
                    resolved_state_dir, enabled=enable_git_history, depth=git_depth
                )
            elif plan.git_history:
                write_git_config(resolved_state_dir, enabled=True, depth=git_depth)

            if plan.start:
                try:
                    existing_config = json.loads(config_path.read_text())
                except (OSError, json.JSONDecodeError):
                    existing_config = {}
                # Honor the user's choices on re-init. Interactive runs reach this
                # branch only after Proceed (a decline downgrades plan.start to
                # False), so the prompted answers in `plan` are explicit and must
                # be applied — summarize/embed included. Non-interactive runs only
                # touch capabilities named by an explicit flag (idempotent).
                if plan.confirm:
                    write_session_config(
                        resolved_state_dir,
                        index=plan.sessions,
                        archive=plan.archive,
                    )
                    apply_extract_engine(resolved_state_dir, project_root, plan.extract)
                else:
                    write_session_config(
                        resolved_state_dir,
                        index=enable_sessions,
                        archive=enable_archive,
                    )
                    if enable_extract is not None:
                        apply_extract_engine(
                            resolved_state_dir, project_root, plan.extract
                        )
                post_init_steps: list[dict[str, object]] = _start_and_watch(
                    project_root=project_root,
                    resolved_state_dir=resolved_state_dir,
                    config_path=config_path,
                    config=existing_config,
                    gitignore_added=False,
                    watch=plan.watch,
                    json_output=json_output,
                    bm25_engine=bm25_engine,
                )
                # Report the TRUE persisted state (session blocks live in
                # config.yaml, not config.json), so the banner reflects the
                # answers just applied rather than a stale default.
                _ex_mode, _si_enabled = read_session_state(resolved_state_dir)
                _emit_init_result(
                    project_root=project_root,
                    resolved_state_dir=resolved_state_dir,
                    config_path=config_path,
                    config=existing_config,
                    gitignore_added=False,
                    post_init_steps=post_init_steps,
                    start_used=True,
                    watch=plan.watch,
                    json_output=json_output,
                    extract_on=_ex_mode not in ("off", False),
                    plugin_present=claude_plugin_installed(project=project_root),
                    sessions_on=_si_enabled,
                    embedding=_preview_embedding(project_root),
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
            resolved_state_dir,
            force=False,
            bm25_language=bm25_language,
            bm25_engine=bm25_engine,
            reranking=reranking_final,
        )
        # On re-init of an existing project (provider block preserved), still
        # honor an explicit --reranking/--no-reranking by merging just that flag.
        if not provider_config_written and enable_reranking is not None:
            _write_reranker_config(resolved_state_dir, reranking_final)
        if force and not provider_config_written and not json_output:
            console.print(
                "[dim]Preserved existing .brainpalace/config.yaml provider "
                "settings (use `brainpalace config` to change providers).[/]"
            )

        # Two INDEPENDENT capabilities resolved by the plan: ARCHIVE (raw
        # transcript backup, free) and INDEX (embeddings, billable). The plan
        # already accounts for explicit flags, --yes, and TTY consent. Two
        # guards remain here:
        #   - only write when we just wrote config.yaml (provider_config_written);
        #     a re-init over an existing project leaves it untouched.
        #   - respect an XDG-inherited session_indexing block unless the user
        #     passed the matching flag explicitly.
        inherited = _existing_session_keys(resolved_state_dir)
        sess: bool | None = plan.sessions
        arch: bool | None = plan.archive
        if not provider_config_written:
            sess = None
            arch = None
        else:
            if not sessions_chosen and "enabled" in inherited:
                sess = None  # respect XDG global default (no explicit choice)
            if enable_archive is None and "archive" in inherited:
                arch = None  # respect XDG archive block
        write_session_config(resolved_state_dir, index=sess, archive=arch)

        # Git-history opt-in (privacy-first; only written when chosen). Guard like
        # the session blocks so a re-init over an existing project leaves a prior
        # choice untouched.
        git_choice = (
            plan.git_history
            if (provider_config_written or enable_git_history is not None)
            else None
        )
        write_git_config(
            resolved_state_dir,
            enabled=git_choice if git_choice else None,
            depth=git_depth,
        )

        # Resolve + persist the session-summarization mode (subagent), and
        # reconcile the Claude Code hooks by plugin presence. Apply on a fresh
        # config write, or whenever --extract/--no-extract was passed explicitly.
        if provider_config_written or enable_extract is not None:
            extract_mode = apply_extract_engine(
                resolved_state_dir, project_root, plan.extract
            )
            if not json_output and extract_mode == "subagent":
                console.print(
                    "[dim]Session summarization: on (subagent — summarized only "
                    "inside Claude Code, free on your Claude Code subscription. "
                    "No server-side paid summarization).[/]"
                )

        # B5: ensure .brainpalace/ is git-ignored for the project.
        gitignore_added = ensure_gitignore_entry(project_root)

        post_init_steps = []

        if plan.start:
            post_init_steps = _start_and_watch(
                project_root=project_root,
                resolved_state_dir=resolved_state_dir,
                config_path=config_path,
                config=config,
                gitignore_added=gitignore_added,
                watch=plan.watch,
                json_output=json_output,
                bm25_engine=bm25_engine,
            )

        _emit_init_result(
            project_root=project_root,
            resolved_state_dir=resolved_state_dir,
            config_path=config_path,
            config=config,
            gitignore_added=gitignore_added,
            post_init_steps=post_init_steps,
            start_used=plan.start,
            watch=plan.watch,
            json_output=json_output,
            extract_on=bool(plan.extract),
            plugin_present=claude_plugin_installed(project=project_root),
            sessions_on=bool(plan.sessions),
            embedding=_preview_embedding(project_root),
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

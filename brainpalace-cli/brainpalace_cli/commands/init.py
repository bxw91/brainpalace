"""Init command for initializing an BrainPalace project."""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def _quiet_server_logs() -> Iterator[None]:
    """Silence bundled-server INFO chatter during in-process calls.

    ``init`` runs the server's estimator and provider preflight in-process; their
    module loggers ("Loading provider config", "Active embedding provider",
    "Loaded N documents from …", …) are server internals, not init UX, and would
    otherwise leak raw log lines into the terminal. Raise the ``brainpalace_server``
    logger to WARNING for the duration and restore the prior level after, so real
    warnings/errors still surface.
    """
    srv = logging.getLogger("brainpalace_server")
    prev = srv.level
    srv.setLevel(logging.WARNING)
    try:
        yield
    finally:
        srv.setLevel(prev)


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
    reranking: bool = False,
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
            # Two-stage reranking is OFF by default. The local cross-encoder
            # needs the heavy `reranker-local` extra (~2.8 GB PyTorch); enable
            # with --reranking (installs the extra) or point reranker.provider at
            # ollama. Stage-1 search works fully without it.
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
    bm25_language: str | None = None,
    bm25_engine: str | None = None,
    reranking: bool | None = None,
) -> bool:
    """Write the project ``config.yaml``, honouring layered resolution.

    Config resolves ``code < global < project`` at runtime, so the project file
    is SPARSE — it stores only what diverges from what would be inherited.

    1. If a GLOBAL config exists at XDG (~/.config/brainpalace/config.yaml), the
       project INHERITS it. Write only explicit per-project divergences passed on
       the CLI (``--language``/``--bm25-engine``/``--reranking``); everything else
       is resolved from global, then code defaults. With no divergences this is an
       (almost) empty file.
    2. If there is NO global config, seed the project with env-detected code
       defaults (see :func:`build_default_provider_config`) so a fresh project is
       self-sufficient. Passed flags win; omitted flags use the code default.

    ``None`` for a flag means "not passed → inherit"; a concrete value means the
    user set it explicitly and it is written.

    Returns True if the file was written, False if it already existed.
    """
    config_path = state_dir / "config.yaml"
    if config_path.exists() and not force:
        return False
    state_dir.mkdir(parents=True, exist_ok=True)

    xdg_global = get_xdg_config_dir() / "config.yaml"
    if xdg_global.is_file():
        # Inherit the global config; persist only explicit divergences.
        sparse: dict[str, object] = {}
        bm: dict[str, object] = {}
        if bm25_language is not None:
            bm["language"] = bm25_language
        if bm25_engine is not None:
            bm["engine"] = bm25_engine
        if bm:
            sparse["bm25"] = bm
        if reranking is not None:
            sparse["reranker"] = {"enabled": reranking}
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(sparse, f, default_flow_style=False, sort_keys=False)
        return True

    # No global → seed env-detected code defaults so the project stands alone.
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            build_default_provider_config(
                bm25_language=bm25_language or "en",
                bm25_engine=bm25_engine or "stem",
                reranking=reranking if reranking is not None else False,
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


def _preflight_lemma(engine: str | None, json_output: bool) -> None:
    """Fail fast when engine=lemma but simplemma is not installed.

    Mirrors the style of _preflight_providers: prints an actionable message
    (the exact pip install command) and exits non-zero BEFORE the server
    starts, so the user gets clear guidance instead of a cryptic mid-index
    crash. ``engine=None`` means the project inherits the engine from
    global/code (not the explicit ``lemma`` opt-in), so the check is skipped.
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
        with _quiet_server_logs():
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


def write_reranker_enabled(state_dir: Path, *, enabled: bool) -> None:
    """Persist ``reranker.enabled`` (deep-merge; preserve other reranker keys)."""
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    rer = data.get("reranker")
    if not isinstance(rer, dict):
        rer = {}
    rer["enabled"] = enabled
    data["reranker"] = rer
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    )


def write_graphrag_doc_extractor(state_dir: Path, *, doc_extractor: str) -> None:
    """Persist ``graphrag.doc_extractor`` (``langextract`` | ``none``).

    Deep-merges into config.yaml so other graphrag keys (enabled/store_type)
    survive. ``none`` is the explicit disable that suppresses the server's
    'langextract not installed' warning for a deliberately-declined feature (D2).
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    graph = data.get("graphrag")
    if not isinstance(graph, dict):
        graph = {}
    graph["doc_extractor"] = doc_extractor
    data["graphrag"] = graph
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    )


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


def _dashboard_from_steps(
    post_init_steps: list[dict[str, object]],
) -> dict[str, object] | None:
    """Extract the dashboard info the start step reported (base_url/started).

    `init --start` runs `start --json` as a subprocess, so the dashboard URL is
    buried in that step's captured stdout. Pull it back out so init can surface a
    clickable URL and open a browser — `start --json` does neither itself.
    """
    for step in post_init_steps:
        if step.get("step") != "start" or step.get("status") != "ok":
            continue
        raw = step.get("stdout")
        if not isinstance(raw, str) or not raw:
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return None
        dash = payload.get("dashboard")
        if isinstance(dash, dict) and dash.get("base_url"):
            return dash
    return None


def _print_and_open_dashboard(
    post_init_steps: list[dict[str, object]],
) -> None:
    """Print a prominent, clickable dashboard URL and open it in a browser.

    The browser is opened only on an interactive terminal (never under CI or a
    piped stdout). Best-effort — a browser failure must not break init output.
    """
    dash = _dashboard_from_steps(post_init_steps)
    if not dash:
        return
    url = dash["base_url"]
    from brainpalace_cli.commands._dashboard_url import render_dashboard_url

    render_dashboard_url(dash, console=console)
    if sys.stdout.isatty():
        import webbrowser  # noqa: PLC0415

        try:
            webbrowser.open(str(url))
        except Exception:
            pass  # best-effort; URL is already printed above


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
                    "dashboard": _dashboard_from_steps(post_init_steps),
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

    # Surface the web dashboard URL prominently and open it — `start --json`
    # (run as a subprocess by init) suppresses both, so init must do it here.
    _print_and_open_dashboard(post_init_steps)

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

    # Only surface "Next steps" when a real action is left for the user (e.g.
    # start the server / add a folder). A fully-successful init ends on the
    # "Done:" summary above — no background-indexing / query boilerplate.
    if todo:
        console.print("\n[dim]Next steps:[/]")
        for item in todo:
            console.print(f"  • {item}")


def _estimate_and_confirm_local(
    project_root: Path, config_yaml: Path, include_code: bool
) -> bool | None:
    """Server-less pre-index token-estimate loop, shown BEFORE any data write.

    Runs the in-process estimate (no server, no enqueue) against the just-written
    project config, prints the breakdown, then lets the user proceed, toggle the
    code/docs scope and re-estimate, or cancel. Returns the final ``include_code``
    to index with, or ``None`` to cancel the whole init (caller rolls back).

    Only the code/docs scope is adjustable here — it's the one init answer that
    actually moves the *embedding* estimate. Provider/session/git answers are
    already resolved into the config at this point.
    """
    from brainpalace_server.services.estimate import estimate_tokens_local

    from .estimate_util import print_token_estimate

    while True:
        try:
            with _quiet_server_logs():
                est = asyncio.run(
                    estimate_tokens_local(
                        str(project_root),
                        include_code=include_code,
                        config_path=str(config_yaml),
                    )
                )
            print_token_estimate(console, est)
        except Exception as exc:  # noqa: BLE001 - advisory only, never block init
            console.print(f"[yellow]Estimate unavailable ({exc}); continuing.[/]")
            return include_code
        console.print(
            f"[dim]Scope: {'code + docs' if include_code else 'docs only'}.[/]"
        )
        action = click.prompt(
            "Proceed with indexing, change scope (code/docs) and re-estimate, "
            "or cancel?",
            type=click.Choice(["proceed", "change", "cancel"]),
            default="proceed",
        )
        if action == "change":
            include_code = not include_code
            continue
        if action == "cancel":
            return None
        return include_code


def _start_and_watch(
    *,
    project_root: Path,
    resolved_state_dir: Path,
    config_path: Path,
    config: dict[str, object],
    gitignore_added: bool,
    watch: str,
    json_output: bool,
    bm25_engine: str | None = "stem",
    include_code: bool = True,
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
        # The pre-index token estimate now runs once, up front in `init_command`
        # (before any data is written), so the scope is already settled here.
        chosen_include_code = include_code
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
                "--include-code" if chosen_include_code else "--no-code",
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
    default=None,
    help=(
        "Server bind host. Default: inherit from global config / code "
        f"({DEFAULT_CONFIG['bind_host']}). Pass to override for this project."
    ),
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
    "--graphrag-extract/--no-graphrag-extract",
    "enable_graphrag_extract",
    default=None,
    help=(
        "Extract a knowledge graph from document text "
        "(installs the optional langextract dep on enable)."
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
    default=None,
    help=(
        "Project default natural language for BM25 indexing (ISO 639-1, e.g. "
        "en, de, hr). Passed → written to bm25.language; omitted → inherit from "
        "global config / code default (en)."
    ),
)
@click.option(
    "--reranking/--no-reranking",
    "enable_reranking",
    default=None,
    help=(
        "Two-stage reranking: a local cross-encoder re-scores the top "
        "candidates for finer relevance ordering. OFF by default — the local "
        "model needs the heavy reranker-local extra (~2.8 GB PyTorch). "
        "--reranking installs that extra and enables it; or set "
        "reranker.provider=ollama for a torch-free reranker. Writes "
        "reranker.enabled to config.yaml."
    ),
)
@click.option(
    "--bm25-engine",
    "bm25_engine",
    default=None,
    type=click.Choice(["stem", "lemma"], case_sensitive=False),
    help=(
        "BM25 stemming engine: 'stem' (Snowball, no extra deps) or 'lemma' "
        "(simplemma, better recall for morphologically-rich languages). Passed "
        "→ written to bm25.engine; omitted → inherit from global config / code "
        "default (stem). engine=lemma requires simplemma: "
        "pip install 'brainpalace[lemma-hr]'."
    ),
)
@click.option(
    "--include-code/--no-code",
    "include_code",
    default=True,
    show_default=True,
    help=(
        "Index source code files alongside documents (default: ON). Use "
        "--no-code for doc-only repos. Applies to the first index and to the "
        "pre-index token estimate."
    ),
)
def init_command(
    path: str | None,
    host: str | None,
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
    enable_graphrag_extract: bool | None,
    enable_graph_migrate: bool | None,
    enable_reranking: bool | None,
    bm25_language: str | None,
    bm25_engine: str | None,
    include_code: bool,
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

        # Pre-existing-index handling. A real, already-initialized project must
        # not be silently rebuilt: an interactive run is offered delete / keep /
        # cancel up front (before any other prompt), and the fresh-init
        # estimate-rollback below only ever removes a `.brainpalace` THIS
        # invocation created. `--force` keeps its existing overwrite semantics.
        preexisting = config_path.exists()
        if preexisting and not force and is_tty:
            console.print(
                f"[yellow].brainpalace already exists[/] at {resolved_state_dir}."
            )
            choice = click.prompt(
                "An index already exists. Delete it and re-init, keep it "
                "(resume), or cancel?",
                type=click.Choice(["keep", "delete", "cancel"]),
                default="keep",
            )
            if choice == "cancel":
                console.print("[dim]Init cancelled.[/]")
                return
            if choice == "delete":
                shutil.rmtree(resolved_state_dir, ignore_errors=True)
                preexisting = False
            # "keep" falls through to the existing already-initialized path.
        # True only when we create `.brainpalace` during this run — guards the
        # estimate-cancel rollback so it never deletes a user's existing index.
        created_brainpalace = not preexisting

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

        # graphrag_extract_ans is set in the consent block when interactive, or
        # left None for non-interactive / --json runs (flag path uses
        # enable_graphrag_extract directly at write time).
        graphrag_extract_ans: bool | None = None

        # archive_ans is set in the consent block when interactive (no flag),
        # or left None for non-interactive / --json runs (flag path uses
        # enable_archive directly at write time).
        archive_ans: bool | None = None

        # _rerank_changed / _rerank_val track the D4 inherited-override gate
        # for reranker.enabled. Initialized here so both the re-init and the
        # fresh-init persistence paths can reference them even on non-interactive
        # runs (where they stay False / None → nothing written, sparse invariant).
        _rerank_changed: bool = False
        _rerank_val: bool | None = None

        # lemma_ans is set in the consent block when interactive and no explicit
        # --bm25-engine flag was passed; left None otherwise (flag path uses
        # bm25_engine directly). A bare "no" stays None → nothing written (sparse
        # invariant); only an active "yes" persists bm25.engine=lemma + installs.
        lemma_ans: bool | None = None

        if plan.confirm:
            embedding = _preview_embedding(project_root)
            plugin_present = claude_plugin_installed(project=project_root)

            # Interactive prompt defaults come from the GLOBAL config when it sets
            # the answer (config resolves code < global < project): the question is
            # pre-filled with the global value and flagged "(from global)". If the
            # user just accepts it, the sparse-write logic below leaves the project
            # config untouched so the value keeps inheriting from global.
            from brainpalace_cli.config_resolve import read_yaml as _ry_cfg
            from brainpalace_cli.config_resolve import resolve as _resolve_cfg

            _gcfg = _ry_cfg(get_xdg_config_dir() / "config.yaml")

            def _global_default(dotpath: str, fallback: bool) -> tuple[bool, bool]:
                """(default, came_from_global) for a boolean question."""
                value, source = _resolve_cfg(dotpath, {}, _gcfg)
                if source == "global":
                    return bool(value), True
                return fallback, False

            def _from_global_note() -> None:
                console.print("  [dim](default taken from your global config)[/]")

            # Granular consent — ask only what an explicit flag didn't already set.
            # Order: summarize first (free baseline recall), then embed (the paid
            # detail upgrade that references the summaries).
            extract_ans: bool = bool(plan.extract)
            if enable_extract is None:
                _gmode, _gmode_from = _resolve_cfg("session_extraction.mode", {}, _gcfg)
                _extract_default = (
                    str(_gmode) != "off" if _gmode_from == "global" else False
                )
                console.print(
                    "\n[bold]Summarize chat sessions?[/] "
                    "(distil past chats into summaries + a decisions digest)\n"
                    "  Free — runs on the Claude Code Haiku subagent (needs the "
                    "Claude Code plugin).\n"
                    "  Makes past chats searchable by topic. Reads full transcripts; "
                    "writes\n  BRAINPALACE_DECISIONS.md. Disable later: --no-extract."
                )
                if _gmode_from == "global":
                    _from_global_note()
                if not plugin_present:
                    # Summarization runs ONLY on the Claude Code plugin's Haiku
                    # subagent. Flag its absence in a distinct colour so the user
                    # knows a "yes" here won't summarize anything until installed.
                    console.print(
                        "  [yellow]⚠ Claude Code plugin not installed[/] — a "
                        "[bold]yes[/] configures summaries, but nothing is "
                        "summarized until you install it: "
                        "[bold]brainpalace install-agent[/]"
                    )
                extract_ans = click.confirm(
                    "Summarize chat sessions?", default=_extract_default
                )

            sessions_ans: bool = bool(plan.sessions)
            if enable_sessions is None:
                from brainpalace_cli.commands.init_plan import (
                    _provider_label,
                    _trim_model_id,
                )

                prov, model = embedding
                tag = f"{_provider_label(prov)} {_trim_model_id(model)}"
                _sess_default, _sess_from = _global_default(
                    "session_indexing.enabled", False
                )
                console.print(
                    "\n[bold]Embed chat sessions too?[/] "
                    "(search the FULL verbatim text, not just summaries)\n"
                    "  Summaries above already make past chats searchable. Embedding "
                    "adds search over\n  the complete raw transcripts — good for exact "
                    f"code/commands — but sends that\n  content to {tag}. Cheap "
                    "(usually a few cents), but a large history\n  adds many tokens. "
                    "Enable later: --sessions."
                )
                if _sess_from:
                    _from_global_note()
                sessions_ans = click.confirm(
                    "Embed chat sessions too?", default=_sess_default
                )
                sessions_chosen = True  # prompt answer is an explicit choice

            if enable_archive is None:
                _arch_default, _arch_from = _global_default(
                    "session_indexing.archive.enabled", True
                )
                console.print(
                    "\n[bold]Back up chat transcripts?[/] "
                    "(free, local copy — no embeddings, no API cost)\n"
                    "  [yellow]⚠ Stores FULL raw transcripts incl. your prompts "
                    "and any secrets[/] under .brainpalace/. Disable later: "
                    "--no-archive."
                )
                if _arch_from:
                    _from_global_note()
                archive_ans = click.confirm(
                    "Back up chat transcripts?", default=_arch_default
                )
            else:
                archive_ans = enable_archive

            git_history_ans: bool = bool(plan.git_history)
            if enable_git_history is None:
                _git_default, _git_from = _global_default("git_indexing.enabled", False)
                console.print(
                    "\n[bold]Index git commit history?[/] "
                    "(make past commits searchable: message + changed-file list)\n"
                    "  [yellow]Note:[/] commit diffs/messages can contain secrets. "
                    "Nothing is copied;\n  chunks reference the commit sha. "
                    "Disable later: --no-git-history."
                )
                if _git_from:
                    _from_global_note()
                git_history_ans = click.confirm(
                    "Index git commit history?", default=_git_default
                )
                if git_history_ans:
                    console.print(
                        "  How far back? Each commit is embedded, so a very large "
                        "history\n  costs more on the first pass. [dim]0 = "
                        "unlimited (entire history).[/]"
                    )
                    git_depth = click.prompt(
                        "How many commits back to index? (0 = unlimited)",
                        default=5000,
                        type=int,
                    )

            # GraphRAG document extraction (#10/#14). doc_extractor=langextract
            # mines entities/relationships from DOC text; needs the optional
            # `langextract` dep. D2: a "no" writes doc_extractor=none (explicit
            # disable, no runtime warning); "yes" installs the extra after consent.
            if enable_graphrag_extract is None:
                from brainpalace_cli import optional_deps

                _gval, _gsrc = _resolve_cfg("graphrag.doc_extractor", {}, _gcfg)
                _ge_default = (
                    (str(_gval) == "langextract") if _gsrc == "global" else False
                )
                console.print(
                    "\n[bold]Extract a knowledge graph from document text?[/] "
                    "(entities + relationships mined from your docs)\n"
                    f"  [yellow]{optional_deps.REGISTRY['graphrag'].download_note}[/]\n"
                    "  Disable later: config graphrag.doc_extractor=none."
                )
                if _gsrc == "global":
                    _from_global_note()
                graphrag_extract_ans = click.confirm(
                    "Extract a knowledge graph from document text?",
                    default=_ge_default,
                )
            else:
                graphrag_extract_ans = enable_graphrag_extract

            # Reranker (#9/#16) — project-overridable; re-ask via the D4 gate.
            # Only a changed answer is persisted (sparse invariant). The gate is
            # skipped when --reranking/--no-reranking was passed explicitly (the
            # flag already decided the value; write_reranker_enabled is called
            # further below on the explicit-flag path).
            if enable_reranking is None:
                from brainpalace_cli.commands.init_plan import inherited_change_gate

                _rerank_val, _rerank_changed = inherited_change_gate(
                    "Reranker", "reranker.enabled", _gcfg
                )

            # BM25 lemma engine (#14) — opt-in that installs the optional
            # `simplemma` dep on yes. Only asked when no explicit --bm25-engine
            # flag decided it. Default to the inherited/global engine when it is
            # `lemma`, else stem (no). D2-style: a "no" writes nothing new (the
            # sparse invariant keeps the project inheriting stem); a "yes" writes
            # bm25.engine=lemma and installs the extra after consent.
            if bm25_engine is None:
                from brainpalace_cli import optional_deps

                _leng, _lsrc = _resolve_cfg("bm25.engine", {}, _gcfg)
                _lemma_default = (str(_leng) == "lemma") if _lsrc == "global" else False
                console.print(
                    "\n[bold]Use lemmatization for BM25 keyword search?[/] "
                    "(better recall for inflected languages)\n"
                    f"  [yellow]{optional_deps.REGISTRY['lemma-hr'].download_note}[/]\n"
                    "  Disable later: config bm25.engine=stem."
                )
                if _lsrc == "global":
                    _from_global_note()
                lemma_ans = click.confirm(
                    "Use lemmatization for BM25 keyword search?",
                    default=_lemma_default,
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
                archive=archive_ans,
                extract=extract_ans,
                git_history=git_history_ans,
                yes=yes,
                is_tty=is_tty,
            )
            summarize: tuple[str, ...] | None = (
                ("subagent",) if plan.extract and plugin_present else None
            )
            # A fresh/force interactive run that will start DEFERS the "init will:"
            # summary + Proceed until AFTER the pre-index estimate (#3), so the
            # estimated cost informs the final decision. Re-init runs (which return
            # before the estimate) and --no-start runs keep the single inline
            # confirmation here.
            _defer_proceed = plan.start and not (config_path.exists() and not force)
            if not _defer_proceed:
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
                    graph_migrate = False  # declining the plan cancels the upgrade

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

            # Persist graphrag doc-extractor choice for an EXISTING project.
            _reinit_graphrag_ans = (
                enable_graphrag_extract
                if enable_graphrag_extract is not None
                else graphrag_extract_ans
            )
            if _reinit_graphrag_ans is not None:
                _doc_ext = "langextract" if _reinit_graphrag_ans else "none"
                write_graphrag_doc_extractor(resolved_state_dir, doc_extractor=_doc_ext)
                if _reinit_graphrag_ans:
                    from brainpalace_cli import optional_deps

                    optional_deps.ensure_extra("graphrag", assume_yes=True)

            # Persist the BM25 lemma opt-in for an EXISTING project too (#14).
            # The fresh-write path below isn't taken on a re-init, so without this
            # the interactive answer would be silently dropped. Explicit flag wins
            # (write below via set_project_bm25); here we handle the interactive
            # answer. Sparse: write engine only for an active "yes", or when the
            # answer diverges from the inherited engine (lemma→stem).
            if bm25_engine is not None:
                from brainpalace_cli.commands.bm25_project import set_project_bm25

                set_project_bm25(resolved_state_dir, engine=bm25_engine)
                if bm25_engine == "lemma":
                    from brainpalace_cli import optional_deps

                    optional_deps.ensure_extra("lemma-hr", assume_yes=True)
            elif lemma_ans is not None:
                from brainpalace_cli.commands.bm25_project import set_project_bm25
                from brainpalace_cli.config_resolve import inherited as _inherited_re
                from brainpalace_cli.config_resolve import read_yaml as _read_yaml_re

                _glob_re = _read_yaml_re(get_xdg_config_dir() / "config.yaml")
                _inh_eng = _inherited_re("bm25.engine", _glob_re)[0]
                _new_eng = "lemma" if lemma_ans else "stem"
                if lemma_ans or _new_eng != (_inh_eng or "stem"):
                    set_project_bm25(resolved_state_dir, engine=_new_eng)
                if lemma_ans:
                    from brainpalace_cli import optional_deps

                    optional_deps.ensure_extra("lemma-hr", assume_yes=True)

            # Persist the archive choice for an EXISTING project too. The
            # plan.start branch below writes it for starts, but a --no-start
            # re-init returns before that — without this the prompted/flagged
            # answer is silently dropped. Explicit flag wins; otherwise the
            # interactive answer applies. (None = bare re-init, leave untouched.)
            _reinit_archive_ans = (
                enable_archive if enable_archive is not None else archive_ans
            )
            if _reinit_archive_ans is not None:
                write_session_config(resolved_state_dir, archive=_reinit_archive_ans)

            # Persist reranker override for an EXISTING project (re-init path).
            # Explicit flag wins (already handled by write_default_provider_config /
            # _write_reranker_config above); only the gate answer is handled here.
            if _rerank_changed:
                write_reranker_enabled(resolved_state_dir, enabled=bool(_rerank_val))

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
                    include_code=include_code,
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

        # Create the state directory + config/log dirs only — the index DATA
        # dirs (chroma/bm25/llamaindex) are deferred until AFTER the pre-index
        # estimate is accepted, so a cancel leaves nothing heavy behind.
        resolved_state_dir.mkdir(parents=True, exist_ok=True)
        (resolved_state_dir / "logs").mkdir(exist_ok=True)

        # Build configuration. --host is now inherit-by-default: only override
        # the code default when explicitly passed.
        config = {
            **DEFAULT_CONFIG,
            "project_root": str(project_root),
        }
        if host is not None:
            config["bind_host"] = host
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
            reranking=enable_reranking,
        )
        # On re-init of an existing project (provider block preserved), still
        # honor an explicit --reranking/--no-reranking by merging just that flag.
        if not provider_config_written and enable_reranking is not None:
            _write_reranker_config(resolved_state_dir, enable_reranking)

        # Explicit reranking opt-in (the --reranking flag, or the interactive D4
        # gate set it true) pulls the heavy local cross-encoder extra (~2.8 GB
        # PyTorch). Install it on opt-in, mirroring graphrag/lemma; a torch-free
        # ollama provider can be configured later instead. A reranking query
        # whose extra is absent degrades to stage-1 with a warning either way.
        _rerank_opt_in = enable_reranking is True or (
            _rerank_changed and bool(_rerank_val)
        )
        if _rerank_opt_in and not json_output:
            from brainpalace_cli import optional_deps

            optional_deps.ensure_extra("reranker-local", assume_yes=True)
        if force and not provider_config_written and not json_output:
            console.print(
                "[dim]Preserved existing .brainpalace/config.yaml provider "
                "settings (use `brainpalace config` to change providers).[/]"
            )

        # SESSION + GIT writes honour layered resolution (code < global <
        # project). Two regimes:
        #   - NO global config → the project is the sole source of truth, so seed
        #     explicit session defaults (archive ON, index per plan) exactly as
        #     before; there is nothing to inherit.
        #   - A global config EXISTS → the project inherits it. Persist only an
        #     explicit CLI flag, or an interactive answer that DIVERGES from the
        #     inherited value. A bare run writes nothing and inherits — so a
        #     global that disables a capability is never clobbered back on.
        from brainpalace_cli.config_resolve import inherited as _inherited
        from brainpalace_cli.config_resolve import read_yaml as _read_yaml_cfg

        _xdg_global_path = get_xdg_config_dir() / "config.yaml"
        _has_global = _xdg_global_path.is_file()
        _glob = _read_yaml_cfg(_xdg_global_path)
        _inh_sessions = _inherited("session_indexing.enabled", _glob)[0]
        _inh_archive = _inherited("session_indexing.archive.enabled", _glob)[0]
        _inh_git = _inherited("git_indexing.enabled", _glob)[0]

        sess: bool | None
        arch: bool | None
        git_choice: bool | None
        if not provider_config_written:
            sess = arch = git_choice = None
        elif not _has_global:
            # Sole source of truth: write the resolved plan defaults explicitly.
            sess = plan.sessions
            arch = plan.archive
            git_choice = (
                enable_git_history
                if enable_git_history is not None
                else (True if plan.git_history else None)
            )
        else:
            # Inherit the global; persist only flags / divergent interactive answers.
            if enable_sessions is not None:
                sess = enable_sessions
            elif sessions_chosen and plan.sessions != _inh_sessions:
                sess = plan.sessions
            else:
                sess = None
            # archive: explicit flag wins; interactive answer persisted when it
            # diverges from the inherited global value; bare run inherits.
            if enable_archive is not None:
                arch = enable_archive
            elif archive_ans is not None and bool(archive_ans) != bool(_inh_archive):
                arch = archive_ans
            else:
                arch = None
            if enable_git_history is not None:
                git_choice = enable_git_history
            elif plan.confirm and bool(plan.git_history) != bool(_inh_git):
                git_choice = plan.git_history
            else:
                git_choice = None
        write_session_config(resolved_state_dir, index=sess, archive=arch)
        write_git_config(resolved_state_dir, enabled=git_choice, depth=git_depth)

        # Persist graphrag doc-extractor choice on the fresh-init path.
        # graphrag_extract_ans is set by the consent block (interactive) or
        # via else-branch when enable_graphrag_extract flag was passed. For
        # non-interactive / --json runs (plan.confirm is False) the variable is
        # still None unless the flag was passed explicitly; None = no write
        # (server default applies, no dep installed).
        _fresh_graphrag_ans = (
            enable_graphrag_extract
            if enable_graphrag_extract is not None
            else (graphrag_extract_ans if plan.confirm else None)
        )
        if _fresh_graphrag_ans is not None:
            _fresh_doc_ext = "langextract" if _fresh_graphrag_ans else "none"
            write_graphrag_doc_extractor(
                resolved_state_dir, doc_extractor=_fresh_doc_ext
            )
            if _fresh_graphrag_ans:
                from brainpalace_cli import optional_deps

                optional_deps.ensure_extra("graphrag", assume_yes=True)

        # Persist the BM25 lemma opt-in on the fresh-init path (#14). The explicit
        # --bm25-engine flag is already written by write_default_provider_config
        # above; here we handle only the interactive answer. Sparse invariant:
        # write bm25.engine only for an active "yes" (lemma), or when the
        # interactive answer DIVERGES from an inherited lemma (lemma→stem). A bare
        # "no" against an inherited stem writes nothing and keeps inheriting.
        if bm25_engine is None and lemma_ans is not None:
            from brainpalace_cli.commands.bm25_project import set_project_bm25

            _inh_engine = _inherited("bm25.engine", _glob)[0]
            _new_engine = "lemma" if lemma_ans else "stem"
            if lemma_ans or _new_engine != (_inh_engine or "stem"):
                # engine-only write (language stays None → inherited; sparse).
                set_project_bm25(resolved_state_dir, engine=_new_engine)
            if lemma_ans:
                from brainpalace_cli import optional_deps

                optional_deps.ensure_extra("lemma-hr", assume_yes=True)

        # Persist reranker override on the fresh-init path (D4 gate or explicit flag).
        # The gate answer (_rerank_changed) takes effect only when enable_reranking was
        # not passed (flag path is already handled by write_default_provider_config /
        # _write_reranker_config above). On non-interactive runs _rerank_changed is
        # False → nothing written → sparse invariant holds.
        if _rerank_changed:
            write_reranker_enabled(resolved_state_dir, enabled=bool(_rerank_val))

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

        # Pre-index token estimate BEFORE writing any index data or starting the
        # server, so a surprising cost can be cancelled with a clean rollback.
        # The config is already fully written, so the estimate honours the
        # resolved provider/git/session choices.
        #
        # Interactive order (#3): ask whether to estimate → estimate
        # (proceed/change/cancel) → show the "init will:" summary → final Proceed.
        # A --yes run keeps a single estimate prompt and no extra confirmation.
        if is_tty and plan.start:
            interactive_gate = plan.confirm  # non --yes run → offer skip + Proceed
            do_estimate = True
            if interactive_gate:
                do_estimate = click.confirm("Estimate token usage first?", default=True)
            if do_estimate:
                chosen = _estimate_and_confirm_local(
                    project_root, resolved_state_dir / "config.yaml", include_code
                )
                if chosen is None:
                    if created_brainpalace:
                        shutil.rmtree(resolved_state_dir, ignore_errors=True)
                        console.print("[dim]Cancelled — removed .brainpalace.[/]")
                    else:
                        console.print("[dim]Cancelled — kept existing .brainpalace.[/]")
                    return
                include_code = chosen
            if interactive_gate:
                # Final gate: the resolved plan, then confirm before starting.
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

        # Index DATA dirs are created only now — after the estimate was accepted
        # (or skipped for a non-interactive run) — so a cancel above leaves no
        # ChromaDB/BM25 scaffolding behind.
        (resolved_state_dir / "data").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "chroma_db").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "bm25_index").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "llamaindex").mkdir(exist_ok=True)

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
                include_code=include_code,
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

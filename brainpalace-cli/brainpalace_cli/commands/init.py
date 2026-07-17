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
from typing import Any, Callable

import click
import yaml
from rich.console import Console
from rich.panel import Panel

from brainpalace_cli.commands.init_plan import (
    InitPlan,
    downgrade_to_config_only,
    format_init_plan,
    resolve_init_plan,
)
from brainpalace_cli.commands.install_mcp import install_mcp, restart_notice
from brainpalace_cli.commands.plugin_detect import (
    claude_plugin_installed,
    maybe_plugin_hint,
)
from brainpalace_cli.commands.session_hooks import (
    install_session_hooks,
    prune_cli_session_hooks,
    prune_extraction_hooks,
)
from brainpalace_cli.lsp_install import EnsureResult, ensure_server
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
    (e.g. enable doc-graph extraction via ``extraction.mode``).

    Task 4e: ``extraction.provider_context_tokens`` is prefilled from the
    model→window map when the picked summarization model is known; left absent
    (0 = runtime floor) for unknown models. Editable after init.
    """
    from brainpalace_server.config.model_windows import window_for

    summ = _pick_provider(_SUMMARIZATION_PREFERENCE, _SUMMARIZATION_FALLBACK)
    tokens = window_for(str(summ.get("provider", "")), str(summ.get("model", "")))

    cfg: dict[str, object] = {
        "embedding": _pick_provider(_EMBEDDING_PREFERENCE, _EMBEDDING_FALLBACK),
        "summarization": summ,
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
    if tokens is not None:
        cfg["extraction"] = {"provider_context_tokens": tokens}
    return cfg


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


def _preview_merged_config(project_root: Path) -> dict[str, Any]:
    """Merged config (global < code) the review grid reads on a FRESH init,
    overlaid with the provider/model detected from the environment so the grid
    shows what the project will actually use. Read-only — writes nothing."""
    from brainpalace_server.config.provider_config import load_merged_config_dict

    merged = dict(load_merged_config_dict(None))
    prov, model = _preview_embedding(project_root)
    emb = dict(merged.get("embedding", {}))
    emb["provider"], emb["model"] = prov, model
    merged["embedding"] = emb
    return merged


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


def _write_ranking_config(state_dir: Path, doc_weight: float) -> None:
    """Idempotently set ``ranking.doc_weight`` in the project config.yaml
    (Phase 6.5a). Preserves all other keys.
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
        except (OSError, ValueError):
            data = {}
    block = data.get("ranking")
    if not isinstance(block, dict):
        block = {}
    block["doc_weight"] = doc_weight
    data["ranking"] = block
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


def _lsp_missing_languages(state_dir: Path) -> list[str]:
    """Languages toggled on in graph_indexing.lsp whose server binary is absent.

    Fail-soft: the CLI consumes the server as a versioned wheel, which may
    predate the ``configured_languages``/``detect_servers`` API — an older (or
    unimportable) server yields an empty list rather than crashing init."""
    try:
        from brainpalace_server.lsp import servers

        return sorted(servers.configured_languages() - servers.detect_servers())
    except Exception:  # noqa: BLE001 — server missing or too old: skip the nudge
        return []


def _preflight_lsp(state_dir: Path, *, interactive: bool, json_output: bool) -> None:
    """When LSP is enabled but the server is missing: interactive → offer to
    install (never auto: assume_yes stays False so `init --yes` can't silently
    mutate the global machine, H4); non-interactive → nudge only (silent in
    --json)."""
    missing = _lsp_missing_languages(state_dir)
    if not missing:
        return
    if not interactive:
        if not json_output:
            click.echo(
                f"LSP is enabled for {', '.join(missing)} but the language server "
                f"isn't installed. Run: brainpalace lsp install"
            )
        return
    for lang in missing:
        result = ensure_server(lang, assume_yes=False, interactive=True)
        if result is EnsureResult.FAILED:
            click.echo(f"LSP: {lang} server install failed (continuing).")


def _provider_needs(
    plan: "InitPlan",
    folders: tuple[str, ...] = (),
    *,
    server_distill: bool = False,
) -> tuple[bool, bool]:
    """(needs_embedding, needs_summarization) for this init run.

    Embedding is exercised by an initial index (watch=auto project root or any
    --folder), session embedding, or git-history indexing. Summarization is
    exercised by document/code indexing.

    Session summarize/extract that init CONFIGURES runs plugin-side on the Claude
    subscription (init's ``apply_extract_engine`` only ever writes
    ``extraction.mode`` = ``subagent``/``off`` — verified init.py:1044-1045), so
    it needs neither server provider. BUT if the resolved config already has
    ``extraction.mode`` in {``auto``, ``provider``}, the SERVER-SIDE distiller
    (``services/session_distill_service.py`` → ``get_summarization_provider`` +
    embedder) is live and will fire on the next session — so ``server_distill``
    forces BOTH needs on regardless of watch/folders (hardening #1).
    """
    will_index = plan.watch != "off" or bool(folders)
    needs_embedding = (
        will_index or bool(plan.sessions) or plan.git_history or server_distill
    )
    needs_summarization = will_index or server_distill
    return needs_embedding, needs_summarization


def _preflight_providers(
    state_dir: Path,
    json_output: bool,
    *,
    needs_embedding: bool = True,
    needs_summarization: bool = True,
) -> None:
    """Validate embedding/summarization providers before starting the server.

    Reuses the server's own validation rules (the CLI bundles the server) so
    there is one source of truth. On a critical error (e.g. a required API key
    is missing) prints the provider, the missing env var, and exits non-zero
    *before* any server start or index job — preventing the mid-init crash
    class. Non-critical warnings are surfaced but do not block.

    Criticals for a provider this run will not actually exercise
    (``needs_embedding``/``needs_summarization`` False) are downgraded to info
    notes instead of blocking (spec Item 1 / G4) — the first operation that
    really embeds/summarizes still fails fast with the same message.
    """
    import os

    try:
        from brainpalace_server.config.provider_config import (
            ValidationSeverity,
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
    except Exception:  # noqa: BLE001 — never block init on the check itself
        return
    finally:
        if prev is None:
            os.environ.pop("BRAINPALACE_CONFIG", None)
        else:
            os.environ["BRAINPALACE_CONFIG"] = prev
        clear_settings_cache()

    needed = {"embedding": needs_embedding, "summarization": needs_summarization}
    blocking = [e for e in errors if needed.get(getattr(e, "provider_type", ""), True)]
    deferred = [
        e for e in errors if not needed.get(getattr(e, "provider_type", ""), True)
    ]

    try:
        blocking_critical = has_critical_errors(blocking)
        deferred_critical = has_critical_errors(deferred)
    except Exception:  # noqa: BLE001 — never block init on the check itself
        return

    if deferred_critical:
        if json_output:
            # JSON parity (hardening #4): agents run `init --json` and would
            # otherwise get zero signal a provider was deferred-but-unconfigured.
            print(
                json.dumps(
                    {
                        "deferred_providers": [
                            {
                                "provider_type": getattr(e, "provider_type", ""),
                                "message": str(e),
                            }
                            for e in deferred
                            if getattr(e, "severity", None)
                            == ValidationSeverity.CRITICAL
                        ]
                    }
                )
            )
        else:
            for e in deferred:
                console.print(
                    f"[dim]Provider not needed yet — {e}. "
                    "The first indexing / session-embed / text-ingest run will "
                    "need it.[/]"
                )

    if not blocking_critical:
        return

    messages = [str(e) for e in blocking]
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
) -> None:
    """Write the session capabilities into config.yaml.

    Deep-merges into the existing config.yaml so the provider/graphrag/storage
    blocks written by ``write_default_provider_config`` (and any XDG-inherited
    ``session_indexing`` keys) are preserved. Only the explicitly-passed
    capabilities are set (``None`` leaves the existing value untouched), so a
    re-init that toggles one capability never clobbers the other. ``index``
    embeds transcripts (billable opt-in); ``archive`` copies raw transcripts
    (durable backup, no embeddings). The distillation engine is set separately
    via ``write_extraction_config`` (``extraction.mode`` governs both doc-graph
    and session distillation). The server reads session capabilities at startup
    via ``load_session_indexing_config``.
    """
    if index is None and archive is None:
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
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def write_extraction_config(state_dir: Path, mode: str) -> None:
    """Write the shared extraction engine mode into config.yaml (sparse, Plan 4).

    Mirrors :func:`write_session_config` but targets the new ``extraction:``
    section (governs both doc-graph and session distillation). Sparse: only
    ``extraction.mode`` is written — all other fields inherit server defaults
    so the project config stays minimal. Deep-merges into the existing
    config.yaml so provider/graphrag/session blocks are preserved.
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    extract_block = data.get("extraction")
    if not isinstance(extract_block, dict):
        extract_block = {}
    extract_block["mode"] = mode
    data["extraction"] = extract_block
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


def _apply_review_edits(state_dir: Path, edits: dict[str, Any]) -> None:
    """Apply the review screen's sparse ``{dotpath: value}`` edits into config.yaml.

    Deep-sets only the user-changed dotpaths, preserving every other key. The
    sparse invariant (write only what diverges) holds because ``edits`` already
    contains only the fields the user actively changed from their resolved value.
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, Any] = {}
    if config_path.exists():
        try:
            loaded = yaml.safe_load(config_path.read_text()) or {}
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
    for dotpath, value in edits.items():
        parts = dotpath.split(".")
        node: dict[str, Any] = data
        for seg in parts[:-1]:
            nxt = node.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                node[seg] = nxt
            node = nxt
        node[parts[-1]] = value
    config_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=str(config_path.parent), suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, config_path)  # atomic on POSIX (finding #13)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _validate_and_warn(config_path: Path) -> None:
    """Validate the config at ``config_path`` and print any errors (finding #3)."""
    from brainpalace_cli.config_schema import (
        format_validation_errors,
        validate_config_file,
    )

    errors = validate_config_file(config_path)
    if errors:
        console.print("\n[bold yellow]Warning:[/] Edited config has validation issues:")
        console.print(format_validation_errors(errors))


def _interactive_on_consent(
    consent_edits: dict[str, Any],
    merged: dict[str, Any],
    *,
    layer: str = "project",
) -> "Callable[[Any], None]":
    """Review-screen consent callback for the global/edit paths: each consent
    field is shown with its warning and prompted explicitly; the choice default is
    None-safe. The default reflects a prior grid edit (``consent_edits`` is the
    shared ``edits`` map), so re-drilling a division shows the value you just set."""
    from brainpalace_cli import config_fields as cf
    from brainpalace_cli.prompt_render import numbered_choice

    def _consent(spec: "cf.FieldSpec") -> None:
        dp = spec.dotpath
        if dp in consent_edits:
            current: Any = consent_edits[dp]
        else:
            current, _src = cf.resolve_value(dp, merged, layer=layer)
        reason = cf.KNOWN_CONSENT_FIELDS.get(dp, "")
        if reason:
            console.print(f"[yellow]⚠ {reason}[/]")
        if spec.widget == "bool":
            new: Any = click.confirm(spec.prompt or dp, default=bool(current))
        else:
            opts = cf.options_for(spec.options_ref) if spec.options_ref else []
            # None-safe default: don't pass "None" as a choice (finding #4).
            default = (
                str(current) if current not in (None, "") else (opts[0] if opts else "")
            )
            new = numbered_choice(spec.prompt or dp, opts, default)
            if dp == "extraction.mode" and new in (
                "provider",
                "auto",
            ):
                console.print(
                    "[yellow]⚠ paid paths also require "
                    "EXTRACTION_PROVIDER_ENABLED=true to drain.[/]"
                )
        if new != current:
            consent_edits[dp] = new

    return _consent


def _fresh_on_consent(
    consent_edits: dict[str, Any],
    merged: dict[str, Any],
    *,
    project_root: Path,
    plugin_present: bool,
) -> "Callable[[Any], None]":
    """Fresh-init grid consent callback. Reproduces the wall's per-field context
    (provider/model tag on embed, plugin warning on summarize, depth follow-up on
    git) on top of the generic warned prompt. The default reflects a prior grid
    edit (``consent_edits`` is the shared ``edits`` map), so re-drilling shows it."""
    from brainpalace_cli import config_fields as cf

    def _consent(spec: "cf.FieldSpec") -> None:
        dp = spec.dotpath
        reason = cf.KNOWN_CONSENT_FIELDS.get(dp, "")
        if reason:
            console.print(f"[yellow]⚠ {reason}[/]")
        if dp == "session_indexing.enabled":
            prov, model = _preview_embedding(project_root)
            console.print(f"  [dim]Embeds raw transcripts via {prov} {model}.[/]")
        if dp == "extraction.mode" and not plugin_present:
            console.print(
                "  [yellow]⚠ Claude Code plugin not installed[/] — "
                "summaries are configured but nothing summarizes until you run "
                "[bold]brainpalace install-agent[/]."
            )
        if dp in consent_edits:
            current: Any = consent_edits[dp]
        else:
            current, _src = cf.resolve_value(dp, merged)
        if spec.widget == "bool":
            new: Any = click.confirm(spec.prompt or dp, default=bool(current))
        else:
            from brainpalace_cli.prompt_render import numbered_choice

            opts = cf.options_for(spec.options_ref) if spec.options_ref else []
            default = (
                str(current) if current not in (None, "") else (opts[0] if opts else "")
            )
            new = numbered_choice(spec.prompt or dp, opts, default)
        if new != current:
            consent_edits[dp] = new
        if dp == "git_indexing.enabled" and new:
            depth = click.prompt(
                "How many commits back to index? (0 = unlimited)",
                default=5000,
                type=int,
            )
            consent_edits["git_indexing.depth"] = depth

    return _consent


def _plan_inputs_from_grid(
    merged: dict[str, Any], edits: dict[str, Any]
) -> dict[str, Any]:
    """Map the grid's resolved values + sparse edits onto resolve_init_plan inputs.

    OPT-IN safety: ``session_indexing.enabled`` and ``git_indexing.enabled`` are
    privacy/cost opt-ins — their code-model defaults (True) must NOT activate on a
    plain grid accept.  Use False unless the user explicitly edited the field in the
    grid (present in ``edits``) or the global config set it (source == "global").
    """
    from brainpalace_cli import config_fields as cf

    def _val(dp: str) -> Any:
        if dp in edits:
            return edits[dp]
        v, _src = cf.resolve_value(dp, merged)
        return v

    def _optin_val(dp: str) -> bool:
        """OPT-IN field: only True when explicitly edited or from global config."""
        if dp in edits:
            return bool(edits[dp])
        _v, _src = cf.resolve_value(dp, merged)
        # "default" means only the code model default — treat as off for fresh init.
        return bool(_v) if _src != "default" else False

    return {
        "sessions": _optin_val("session_indexing.enabled"),
        "archive": bool(_val("session_indexing.archive.enabled")),
        "extract": str(_val("extraction.mode")) != "off",
        "git_history": _optin_val("git_indexing.enabled"),
        "git_depth": edits.get("git_indexing.depth"),
        "graphrag_extract_mode": edits.get("extraction.mode"),
    }


def _reconcile_optional_deps(edits: dict[str, Any]) -> None:
    """Install the heavy extras a review edit just opted into (reranker/lemma)."""
    from brainpalace_cli import optional_deps

    if edits.get("reranker.enabled") is True:
        optional_deps.ensure_extra("reranker-local", assume_yes=True)
    if edits.get("bm25.engine") == "lemma":
        optional_deps.ensure_extra("lemma-hr", assume_yes=True)


def _run_global_config_edit(*, json_output: bool, yes: bool) -> None:
    """`init --global`: edit the global XDG config.yaml via the review screen."""
    from brainpalace_cli import config_review
    from brainpalace_cli.config_resolve import global_config_path, read_yaml
    from brainpalace_cli.xdg_paths import get_xdg_config_dir

    is_tty = _stdin_is_tty() and not json_output
    if not (is_tty and not yes):
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "status": "noop",
                        "reason": "--global is interactive; nothing to edit",
                    }
                )
            )
        else:
            console.print("[dim]--global is interactive; nothing to edit.[/]")
        return

    xdg_dir = get_xdg_config_dir()
    xdg_dir.mkdir(parents=True, exist_ok=True)
    merged = read_yaml(global_config_path())
    consent_edits: dict[str, Any] = {}
    on_consent = _interactive_on_consent(consent_edits, merged, layer="global")
    field_edits = config_review.review_config(
        xdg_dir, on_consent=on_consent, layer="global", edits=consent_edits
    )
    if field_edits is None:
        console.print("[dim]Cancelled — no changes written.[/]")
        return
    all_edits = field_edits
    if all_edits:
        _apply_review_edits(xdg_dir, all_edits)
        _reconcile_optional_deps(all_edits)
        gcfg = xdg_dir / "config.yaml"
        _validate_and_warn(gcfg)
        console.print(f"[green]Global config updated: {gcfg}[/]")
    else:
        console.print("[dim]No changes.[/]")
    _global_dashboard_settings_step(xdg_dir)


def _global_dashboard_settings_step(xdg_dir: Path) -> None:
    """Global-only ``dashboard.*`` (autostart/port).

    Written sparsely via ``_apply_review_edits`` + validated.

    Control-plane (dashboard process) settings — fleet-wide, NOT per-project
    config; edited here AND on the dashboard Settings tab (the two renderers).
    Keys MUST be canonical (∈ config_schema.DASHBOARD_KNOWN_FIELDS) so the two
    surfaces can't drift.  Any future prompt added here must use a canonical key.
    """
    from brainpalace_cli import config_schema as cs
    from brainpalace_cli.config_resolve import read_yaml

    gcfg = xdg_dir / "config.yaml"
    if not click.confirm(
        "Configure the web dashboard (autostart/port)?", default=False
    ):
        return
    cur = read_yaml(gcfg).get("dashboard", {}) or {}
    autostart = click.confirm(
        "Auto-start the web dashboard when you run 'brainpalace start'?",
        default=bool(cur.get("autostart", True)),
    )
    port = click.prompt(
        "Dashboard port",
        type=click.IntRange(min=1, max=65535),
        default=int(cur.get("port", 8787)),
    )
    written = {"dashboard.autostart": autostart, "dashboard.port": port}
    assert all(dp.split(".", 1)[1] in cs.DASHBOARD_KNOWN_FIELDS for dp in written)
    _apply_review_edits(xdg_dir, written)
    _validate_and_warn(gcfg)


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


def write_extraction_mode(state_dir: Path, *, mode: str) -> None:
    """Persist ``extraction.mode`` (``subagent`` | ``off``).

    Deep-merges into config.yaml so other keys survive. ``off`` is the
    explicit disable (cost-safe default). ``subagent`` enables free doc-graph
    + session extraction via Claude Code Haiku (no extra dep, no API cost).
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded
    extraction = data.get("extraction")
    if not isinstance(extraction, dict):
        extraction = {}
    extraction["mode"] = mode
    data["extraction"] = extraction
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
    """Return ``(extraction.mode, session_indexing.enabled)`` from config.yaml.

    Session capabilities live in ``config.yaml``; the re-init result banner reads
    them here to report the true state. ``extraction.mode`` is the sole engine
    selector for both doc-graph and session distillation. Defaults to
    ``("off", False)`` when absent/unreadable.
    """
    config_path = state_dir / "config.yaml"
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return ("off", False)
    if not isinstance(data, dict):
        return ("off", False)
    extract = data.get("extraction")
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
    """Remove all CLI-installed BrainPalace hooks from ``settings.json``.

    On the plugin-present path the plugin owns every hook (SessionStart reminder +
    SessionEnd/UserPromptSubmit extraction) via ``plugin.json``; a CLI copy would
    double-run — most visibly a duplicated SessionStart guidance block. So this
    prunes both the extraction hooks AND any CLI-installed SessionStart shim,
    self-healing an older install. No-op when settings.json is absent/unparseable.
    """
    settings_path = home / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data = prune_extraction_hooks(data)
    data = prune_cli_session_hooks(data)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def apply_extract_engine(
    state_dir: Path,
    project_root: Path,
    enabled: bool,
    home: Path | None = None,
    *,
    graphrag_extract: bool = False,
    graphrag_mode: str | None = None,
) -> str:
    """Persist the extraction mode + reconcile Claude Code hooks.

    ``enabled`` is the resolved ``plan.extract`` (session summarization).
    ``graphrag_extract`` is the doc-graph extraction answer. ``graphrag_mode``,
    when given (the interactive engine picker), selects the doc-graph engine
    explicitly (``subagent`` | ``auto`` | ``provider``); since ``extraction.mode``
    is shared, that engine also drives session distillation. ``extraction.mode``
    is set to ``subagent`` when EITHER signal is on without an explicit engine,
    and to ``off`` only when both are off.

    Hook reconciliation follows the plugin-presence rule:
    - **Plugin present** → the plugin owns all 3 hooks. We only prune old
      CLI-installed extraction hooks and do NOT install the reminder (avoids a
      double SessionStart).
    - **Plugin absent** (CLI/MCP only) → install the SessionStart reminder via
      :func:`install_session_hooks` (which also prunes old extraction hooks).

    Returns the resolved mode (``off`` | ``subagent`` | ``auto`` | ``provider``).
    """
    if graphrag_mode and graphrag_mode != "off":
        mode = graphrag_mode  # explicit engine picked at init (shared by both)
    elif enabled or graphrag_extract:
        mode = "subagent"
    else:
        mode = "off"
    # extraction.mode governs both doc-graph and session distillation.
    write_extraction_config(state_dir, mode)
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


_GLOB_METACHARS = set("*?[")


def _normalize_exclude_input(raw: str, target: Path) -> str:
    """Turn a typed value into an ``indexing.exclude_patterns`` glob.

    A value containing a glob metachar is stored verbatim; a plain name is
    anchored so ``fnmatch`` (``**``→``*`` on the absolute path) actually matches
    it: an existing dir → ``**/<name>/**``, an existing file → ``**/<name>``,
    otherwise a dotted leaf is treated as a file, else a folder."""
    raw = raw.strip()
    if any(c in raw for c in _GLOB_METACHARS):
        return raw
    name = raw.strip("/")
    p = target / name
    if p.is_dir():
        return f"**/{name}/**"
    if p.is_file():
        return f"**/{name}"
    return f"**/{name}" if "." in Path(name).name else f"**/{name}/**"


def _read_project_excludes(state_dir: Path) -> list[str]:
    """Raw project-file ``indexing.exclude_patterns`` (extras only; [] if absent)."""
    cfg = state_dir / "config.yaml"
    try:
        data = yaml.safe_load(cfg.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    block = data.get("indexing") if isinstance(data, dict) else None
    pats = block.get("exclude_patterns") if isinstance(block, dict) else None
    return list(pats) if isinstance(pats, list) else []


def _write_project_excludes(state_dir: Path, patterns: list[str] | None) -> None:
    """Sparsely set ``indexing.exclude_patterns``; remove the key (and an empty
    ``indexing`` block) when ``patterns`` is falsy. Preserves all other keys."""
    cfg = state_dir / "config.yaml"
    data: dict[str, Any] = {}
    if cfg.exists():
        try:
            loaded = yaml.safe_load(cfg.read_text()) or {}
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, yaml.YAMLError):
            data = {}
    block = data.get("indexing")
    if not isinstance(block, dict):
        block = {}
    if patterns:
        block["exclude_patterns"] = patterns
    else:
        block.pop("exclude_patterns", None)
    if block:
        data["indexing"] = block
    else:
        data.pop("indexing", None)
    with open(cfg, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def _gitignore_remove_line(target: Path, line: str) -> bool:
    """Remove a single ``line`` from ``target/.gitignore``. Returns True if removed."""
    gi = target / ".gitignore"
    if not gi.exists():
        return False
    lines = gi.read_text().splitlines()
    keep = [ln for ln in lines if ln.strip() != line.strip()]
    if len(keep) == len(lines):
        return False
    gi.write_text("\n".join(keep) + ("\n" if keep else ""))
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
    await_first_start: bool = False,
    folders: tuple[str, ...] = (),
    mcp_installed: bool = False,
    mcp_notice: str | None = None,
) -> None:
    """Print the init result, including any post-init step outcomes."""
    # Register the project in the durable fleet store so the dashboard can list
    # and start it even when init did not start the server. `brainpalace start`
    # registers on the start path; this closes the config-only / --no-start gap.
    # Best-effort: a registry write must never abort an otherwise-successful init.
    try:
        from brainpalace_cli import known_projects

        known_projects.remember(project_root, resolved_state_dir, project_root.name)
    except Exception:
        pass

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
                    "folders": list(folders),
                    "dashboard": _dashboard_from_steps(post_init_steps),
                    "await_first_start": await_first_start,
                    "mcp": (
                        {"installed": mcp_installed, "notice": mcp_notice}
                        if mcp_installed
                        else None
                    ),
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
    if await_first_start:
        # Deferred (plugin) init: config saved, server NOT running, and it will
        # NOT auto-start until the user starts it once. Spell that out.
        todo.append(
            "Config saved — the server is [bold]not running[/]. Review it (the "
            "dashboard or [bold]brainpalace config show[/]), then start it the "
            "first time yourself: [bold]brainpalace start[/] (or the dashboard "
            "Instances → Start). It will not auto-start until you do."
        )
    elif not start_used:
        todo.append("Run [bold]brainpalace start[/] to start the server")
    elif started_ok:
        done.append("Server started.")
    if watch == "off":
        if folders:
            for f in folders:
                todo.append(f"Run [bold]brainpalace folders add {f}[/] to index it")
        else:
            todo.append("Run [bold]brainpalace folders add <path>[/] to index a folder")
    elif watched_ok:
        _targets = ", ".join(folders) if folders else str(project_root)
        done.append(f"Folder watched + initial indexing enqueued: {_targets}")

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

    # D15/D17: writing .mcp.json configures the project but does not populate
    # this running session — the tools arrive next session, after the user
    # approves the project's MCP servers. Surface that now, not silently.
    if mcp_installed and mcp_notice:
        console.print(f"\n[dim]MCP:[/] {mcp_notice}")

    # Only surface "Next steps" when a real action is left for the user (e.g.
    # start the server / add a folder). A fully-successful init ends on the
    # "Done:" summary above — no background-indexing / query boilerplate.
    if todo:
        console.print("\n[dim]Next steps:[/]")
        for item in todo:
            console.print(f"  • {item}")

    # Point AI agents at the canonical usage guidance (search rules + modes).
    console.print(
        "\n[dim]AI agents: run [bold]brainpalace ai-guide[/] for search rules "
        "& modes.[/]"
    )

    # If Claude Code is set up but the plugin is missing, the CLI alone does not
    # wire the Claude Code integration (research agent, subagent guard, guidance).
    hint = maybe_plugin_hint()
    if hint:
        console.print("\n[dim]" + hint + "[/]")


def _prompt_index_target(
    project_root: Path,
    folders: tuple[str, ...],
    include_code: bool,
    *,
    folders_explicit: bool,
    code_explicit: bool,
) -> tuple[tuple[str, ...], bool]:
    """Interactive index-target picker, asked BEFORE the config-review grid.

    Two questions: which folder to index (a path relative to the project root,
    or ``.`` / empty to keep the whole project — today's default) and its index
    type (code + docs, or docs only). The answers populate the SAME ``folders``
    / ``include_code`` the ``-F`` / ``--include-code`` flags feed, so every
    downstream consumer (token estimate, provider preflight, ``folders add``)
    targets the choice with no new plumbing.

    Explicit flags win and suppress their prompt (``folders_explicit`` /
    ``code_explicit``). Keeping the root default leaves ``folders`` empty, so the
    index target stays ``project_root`` via the existing empty-folders fallbacks
    — a bare Enter reproduces plain ``init`` exactly. Type maps to the existing
    binary: both → ``include_code=True``, docs → ``False`` (no code-only state).
    """
    console.print("\n[bold]What should BrainPalace index?[/]")
    if not folders_explicit:
        while True:
            answer = click.prompt(
                "Folder to index (path relative to the project root, or . for "
                "the whole project)",
                default=".",
            ).strip()
            if answer in ("", ".", "./"):
                break  # keep root default → leave `folders` empty (today's path)
            candidate = (project_root / answer).resolve()
            if candidate.is_dir():
                folders = (str(candidate),)
                break
            console.print(f"[yellow]Not a folder:[/] {candidate}. Try again.")
    if not code_explicit:
        kind = click.prompt(
            "Index type",
            type=click.Choice(["both", "docs"]),
            default="both",
        )
        include_code = kind == "both"
    return folders, include_code


def _estimate_and_confirm_local(
    targets: list[Path],
    config_yaml: Path,
    include_code: bool,
    *,
    interactive: bool = True,
    state_dir: Path | None = None,
    project_root: Path | None = None,
) -> bool | None:
    """Interactive pre-index token-estimate + exclude-trimming loop.

    Shows a per-top-level-folder breakdown of the init target, then a menu to
    add/remove excludes (BrainPalace config or .gitignore), reset the BP exclude
    list, re-estimate, proceed, or cancel. Returns ``include_code`` unchanged on
    proceed, or ``None`` to cancel the whole init (caller rolls back).

    ``interactive`` gates the menu: a non-interactive run (``--yes``/CI) prints
    the estimate once and proceeds. Config excludes are project-global; .gitignore
    edits write raw lines to the primary target's .gitignore and are permanent.
    """
    from brainpalace_server.services.estimate import estimate_tokens_local

    from .estimate_util import print_folder_estimate

    state_dir = state_dir or config_yaml.parent
    primary = targets[0] if targets else Path.cwd()
    project_root = project_root or primary
    baseline_excludes = _read_project_excludes(state_dir)
    session_gitignore: list[str] = []

    def _run() -> list[dict[str, Any]] | None:
        out: list[dict[str, Any]] = []
        # A live spinner so the user knows the scan+tokenize is working (it can
        # take several seconds on a first, cold-cache run of a large tree). No-op
        # on a non-TTY (piped/CI); the numbers below are what matters.
        try:
            with console.status(
                "[dim]Scanning files & estimating tokens…[/]", spinner="dots"
            ):
                for target in targets:
                    with _quiet_server_logs():
                        est = asyncio.run(
                            estimate_tokens_local(
                                str(target),
                                include_code=include_code,
                                config_path=str(config_yaml),
                            )
                        )
                    out.append(est)
        except Exception as exc:  # noqa: BLE001 - advisory only, never block init
            console.print(f"[yellow]Estimate unavailable ({exc}); continuing.[/]")
            return None
        return out

    ests = _run()
    stale = False
    while True:
        if ests is not None:
            for est in ests:
                print_folder_estimate(
                    console,
                    est,
                    stale=stale,
                    bp_excludes=_read_project_excludes(state_dir),
                    session_gitignore=session_gitignore,
                )
        if not interactive:
            return include_code

        console.print(
            "\n  1) add file/folder to ignore\n"
            "  2) remove file/folder from ignore\n"
            "  3) reset BrainPalace ignore list (BP config only)\n"
            "  4) re-estimate tokens\n"
            "  5) proceed with indexing\n"
            "  6) cancel initialization"
        )
        action = click.prompt(
            "Choose",
            type=click.Choice(["1", "2", "3", "4", "5", "6"]),
            default="5",
        )

        if action == "1":
            raw = click.prompt(
                "Type full file/folder name, or a glob to match several", default=""
            ).strip()
            if not raw:
                continue
            where = (
                click.prompt(
                    "Save to [B]rainPalace config or [G]itignore? (Enter = cancel)",
                    default="",
                )
                .strip()
                .lower()
            )
            if where in ("b", "brainpalace"):
                pat = _normalize_exclude_input(raw, primary)
                cur = _read_project_excludes(state_dir)
                if pat not in cur:
                    _write_project_excludes(state_dir, cur + [pat])
                stale = True
            elif where in ("g", "gitignore"):
                console.print(
                    "[yellow]This change will be saved now into your .gitignore "
                    "file. It is permanent — undo only by editing .gitignore "
                    "manually later.[/]"
                )
                if ensure_gitignore_entry(primary, entry=raw):
                    session_gitignore.append(raw)
                stale = True
            continue

        if action == "2":
            raw = click.prompt(
                "Type the file/folder name or pattern to remove", default=""
            ).strip()
            if not raw:
                continue
            where = (
                click.prompt(
                    "Remove from [B]rainPalace config or [G]itignore? (Enter = cancel)",
                    default="",
                )
                .strip()
                .lower()
            )
            if where in ("b", "brainpalace"):
                pat = _normalize_exclude_input(raw, primary)
                cur = _read_project_excludes(state_dir)
                new = [p for p in cur if p not in (pat, raw)]
                if new != cur:
                    _write_project_excludes(state_dir, new or None)
                stale = True
            elif where in ("g", "gitignore"):
                if _gitignore_remove_line(primary, raw):
                    session_gitignore[:] = [
                        ln for ln in session_gitignore if ln.strip() != raw.strip()
                    ]
                stale = True
            continue

        if action == "3":
            if click.confirm(
                "Reset the BrainPalace ignore list to its pre-init state?",
                default=False,
            ):
                _write_project_excludes(state_dir, baseline_excludes or None)
                stale = True
            continue

        if action == "4":
            ests = _run()
            stale = False
            continue

        if action == "5":
            total_files = sum(e.get("files", 0) for e in ests) if ests else 0
            if ests is not None and total_files == 0:
                console.print("[yellow]Nothing left to index.[/]")
                continue
            return include_code

        if action == "6":
            return None


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
    force_budget: bool = False,
    needs_embedding: bool = True,
    needs_summarization: bool = True,
    folders: tuple[str, ...] = (),
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
    _preflight_providers(
        resolved_state_dir,
        json_output,
        needs_embedding=needs_embedding,
        needs_summarization=needs_summarization,
    )

    # LSP pre-flight: if graph indexing / LSP is enabled but the language server
    # is missing, offer to install it (interactive) or nudge (non-interactive).
    # init NEVER auto-installs — assume_yes is not threaded here (H4).
    _preflight_lsp(
        resolved_state_dir, interactive=_stdin_is_tty(), json_output=json_output
    )

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
            folders=folders,
        )
        raise SystemExit(1)

    if watch != "off":
        # The pre-index token estimate now runs once, up front in `init_command`
        # (before any data is written), so the scope is already settled here.
        chosen_include_code = include_code
        targets = list(folders) if folders else [str(project_root)]
        for target in targets:
            if not json_output:
                console.print(
                    f"[dim]Registering folder + enqueuing initial indexing… "
                    f"({target})[/]"
                )
            watch_argv = [
                *_brainpalace_argv(),
                "folders",
                "add",
                target,
                "--watch",
                watch,
                "--include-code" if chosen_include_code else "--no-code",
            ]
            if force_budget:
                watch_argv.append("--force-budget")
            if folders:
                watch_argv.append("--allow-external")
            watch_result = _run_subcommand(
                watch_argv, step="watch", json_output=json_output
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
                    folders=folders,
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
        "Server bind host. Default: inherit from global config / code (127.0.0.1). "
        "Pass to override for this project (writes bind.bind_host to config.yaml)."
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
@click.option(
    "--global",
    "global_",
    is_flag=True,
    help="Edit the global ~/.config/brainpalace/config.yaml (XDG) that all "
    "projects inherit, through the same review screen. No project index/start.",
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
    "--defer-activation",
    "--plugin-managed",
    "defer_activation",
    is_flag=True,
    help=(
        "Configure the project but leave it NOT running: implies --no-start and "
        "--no-watch, and writes a one-shot activation marker "
        "(cli.await_first_start) so passive vectors (the SessionStart hook, MCP "
        "--ensure-server) do NOT auto-start it until the user starts it once "
        "(`brainpalace start` or the dashboard Start). Used by the plugin setup "
        "path. An explicit --start overrides it. No effect on an already-started "
        "project."
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
    "--mcp/--no-mcp",
    "enable_mcp",
    default=True,
    help=(
        "Write BrainPalace's MCP server into the project's .mcp.json "
        "(merged, never clobbering other servers already declared there). ON "
        "by default — unlike session embedding, this costs no money, only "
        "~2,360 tokens of context in a project that already runs "
        "BrainPalace. Pass --no-mcp to opt out. Written on every init path, "
        "including --defer-activation: .mcp.json is configuration, not "
        "activation, so it starts nothing. Tools appear next session, after "
        "you approve the project's MCP servers."
    ),
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
        "(LLM triplet extraction via extraction.mode)."
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
    "--doc-weight",
    type=click.FloatRange(0.0, 1.0),
    default=None,
    help=(
        "Trust of docs vs code in search (0.0=exclude … 0.5=default … "
        "1.0=equal). Writes ranking.doc_weight to config.yaml non-interactively "
        "(the field is also editable in the review grid's Retrieval Ranking "
        "division)."
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
@click.option(
    "--folder",
    "-F",
    "folders",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    help=(
        "Register + index ONLY this folder at start (repeatable), instead of "
        "the whole project root. Paths outside the project tree are allowed. "
        "Implies watching the given folders; incompatible with --no-watch/"
        "--watch off."
    ),
)
def init_command(
    path: str | None,
    host: str | None,
    port: int | None,
    force: bool,
    global_: bool,
    json_output: bool,
    state_dir: str | None,
    force_monorepo_root: bool,
    start: bool | None,
    defer_activation: bool,
    watch: str | None,
    no_watch: bool,
    yes: bool,
    enable_mcp: bool,
    enable_sessions: bool | None,
    enable_archive: bool | None,
    enable_extract: bool | None,
    enable_git_history: bool | None,
    enable_graphrag_extract: bool | None,
    enable_graph_migrate: bool | None,
    enable_reranking: bool | None,
    doc_weight: float | None,
    bm25_language: str | None,
    bm25_engine: str | None,
    include_code: bool,
    folders: tuple[str, ...],
) -> None:
    """Initialize a new BrainPalace project.

    Creates the .brainpalace/ directory structure and writes
    a default config.yaml file.

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
      brainpalace init --no-mcp         # Don't write .mcp.json (MCP tools)
      brainpalace init --no-watch       # Start, but do not index/watch the folder
      brainpalace init --path /my/proj  # Initialize a specific project
      brainpalace init --force          # Overwrite existing config
    """
    try:
        # Trigger one-time migration from legacy ~/.brainpalace to XDG dirs
        migrate_legacy_paths()

        # --global: edit the XDG global config and return. No project root,
        # no index, no start. Must be INSIDE the try so migrate_legacy_paths()
        # always runs first (finding #5).
        if global_:
            _run_global_config_edit(json_output=json_output, yes=yes)
            return

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

        # --defer-activation (plugin path): configure but do NOT start. An
        # explicit --start beats it (the user is activating now); otherwise force
        # config-only (no start, no watch) and arm the activation marker below.
        defer_activation_effective = defer_activation and start is None
        if defer_activation_effective:
            start = False
            no_watch = True

        if folders and (no_watch or watch == "off"):
            raise click.UsageError(
                "--folder/-F implies watching the given folders; drop "
                "--no-watch/--watch off, or drop -F."
            )

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
        config_path = resolved_state_dir / "config.yaml"

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
        # The engine chosen by the interactive picker (off/subagent/auto/provider);
        # None on non-interactive/flag runs (the bool flag maps to subagent/off).
        graphrag_extract_mode: str | None = None

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

        # grid_edits collects the sparse edit map from the review grid on the
        # interactive fresh-init path (consent_edits ∪ field_edits). Initialized
        # to empty so the downstream "if plan.confirm and grid_edits:" writer is
        # safe on non-interactive / --yes paths where plan.confirm is False.
        grid_edits: dict[str, Any] = {}

        # Interactive index-target picker — asked FIRST, before the config grid.
        # Fresh interactive runs that will actually index (created .brainpalace
        # this run, will start + watch) ask which folder + which type to index,
        # populating the same `folders` / `include_code` the -F / --include-code
        # flags feed. Explicit flags win (no prompt). See _prompt_index_target.
        if created_brainpalace and plan.confirm and plan.start and plan.watch != "off":
            from click.core import ParameterSource

            _ctx = click.get_current_context()
            _folders_explicit = (
                _ctx.get_parameter_source("folders") == ParameterSource.COMMANDLINE
            )
            _code_explicit = (
                _ctx.get_parameter_source("include_code") == ParameterSource.COMMANDLINE
            )
            folders, include_code = _prompt_index_target(
                project_root,
                folders,
                include_code,
                folders_explicit=_folders_explicit,
                code_explicit=_code_explicit,
            )

        if plan.confirm:
            plugin_present = claude_plugin_installed(project=project_root)
            embedding = _preview_embedding(project_root)
            _merged = _preview_merged_config(project_root)

            from brainpalace_cli import config_review

            consent_edits: dict[str, Any] = {}
            on_consent = _fresh_on_consent(
                consent_edits,
                _merged,
                project_root=project_root,
                plugin_present=plugin_present,
            )
            field_edits = config_review.review_config(
                resolved_state_dir,
                on_consent=on_consent,
                layer="project",
                edits=consent_edits,
            )
            if field_edits is None:
                if created_brainpalace:
                    shutil.rmtree(resolved_state_dir, ignore_errors=True)
                console.print("[dim]Cancelled — no changes written.[/]")
                return
            grid_edits = field_edits

            pin = _plan_inputs_from_grid(_merged, grid_edits)
            git_depth = pin["git_depth"]
            graphrag_extract_mode = pin["graphrag_extract_mode"]
            graphrag_extract_ans = (
                None
                if graphrag_extract_mode is None
                else graphrag_extract_mode != "off"
            )
            sessions_chosen = "session_indexing.enabled" in grid_edits
            archive_ans = pin["archive"]

            plan = resolve_init_plan(
                start=start,
                watch=watch,
                no_watch=no_watch,
                sessions=pin["sessions"],
                archive=pin["archive"],
                extract=pin["extract"],
                git_history=pin["git_history"],
                yes=yes,
                is_tty=is_tty,
            )

            # Graph-store upgrade is a migration ACTION, not a config field — ask it
            # after the grid (only for a legacy 'simple'-store re-init).
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
                _gate_prompt = (
                    "Start the BrainPalace server now?"
                    if (plan.start and start is None)
                    else "Proceed?"
                )
                if not click.confirm(_gate_prompt, default=True):
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

            # Resolve graphrag-extract answer for this re-init. Passed into
            # apply_extract_engine calls below so extraction.mode is set by
            # one writer that combines session-extract + doc-graph signals.
            _reinit_graphrag_ans = (
                enable_graphrag_extract
                if enable_graphrag_extract is not None
                else graphrag_extract_ans
            )

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

            # Task 4: Unified editor for the re-init path — same review screen as
            # fresh init. The real on_consent is supplied so billable/secret fields
            # route to a warned prompt (not silently skipped). Cancelling here
            # returns without touching any config (idempotent abort).
            if is_tty and not yes:
                from brainpalace_server.config.provider_config import (
                    load_merged_config_dict,
                )

                from brainpalace_cli import config_review

                _merged = load_merged_config_dict(resolved_state_dir / "config.yaml")
                _consent_edits: dict[str, Any] = {}
                _on_consent = _interactive_on_consent(_consent_edits, _merged)
                _field_edits = config_review.review_config(
                    resolved_state_dir,
                    on_consent=_on_consent,
                    layer="project",
                    edits=_consent_edits,
                )
                if _field_edits is None:
                    console.print("[dim]Cancelled — no changes written.[/]")
                    return
                _all_edits = _field_edits
                if _all_edits:
                    _apply_review_edits(resolved_state_dir, _all_edits)
                    _reconcile_optional_deps(_all_edits)
                    _validate_and_warn(resolved_state_dir / "config.yaml")

            if plan.start:
                try:
                    existing_config = yaml.safe_load(config_path.read_text()) or {}
                except (OSError, Exception):
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
                    apply_extract_engine(
                        resolved_state_dir,
                        project_root,
                        plan.extract,
                        graphrag_extract=bool(_reinit_graphrag_ans),
                        graphrag_mode=graphrag_extract_mode,
                    )
                else:
                    write_session_config(
                        resolved_state_dir,
                        index=enable_sessions,
                        archive=enable_archive,
                    )
                    if enable_extract is not None or _reinit_graphrag_ans is not None:
                        apply_extract_engine(
                            resolved_state_dir,
                            project_root,
                            plan.extract,
                            graphrag_extract=bool(_reinit_graphrag_ans),
                        )
                # extraction.mode auto/provider => the server distiller (not the
                # plugin subagent) will summarize+embed; those keys are
                # genuinely needed. Read AFTER the config writes above so this
                # run's just-persisted mode is seen.
                _extract_mode, _ = read_session_state(resolved_state_dir)
                _server_distill = _extract_mode not in ("off", "subagent")
                needs_embedding, needs_summarization = _provider_needs(
                    plan, folders, server_distill=_server_distill
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
                    needs_embedding=needs_embedding,
                    needs_summarization=needs_summarization,
                    folders=folders,
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
                    folders=folders,
                )
                return
            # --no-start re-init: apply_extract_engine not called above, so
            # write extraction.mode here if a graphrag-extract answer was given
            # or session-extract was explicitly passed.
            if _reinit_graphrag_ans is not None or enable_extract is not None:
                apply_extract_engine(
                    resolved_state_dir,
                    project_root,
                    plan.extract,
                    graphrag_extract=bool(_reinit_graphrag_ans),
                )
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

        # Phase L: write a default config.yaml (provider settings) with
        # graphrag.enabled=true so new projects get code-graph indexing
        # without needing `brainpalace config wizard`. Idempotent: skip
        # if config.yaml already exists. NOTE: never pass force here — a
        # re-init with --force must preserve the user's provider/embedding/
        # summarization/storage/graphrag edits in config.yaml (use
        # `brainpalace config` to change providers). Clobbering them on
        # --force was a data-loss papercut.
        # Bind settings (--host / --port) are written into the config.yaml
        # bind: section below after the provider block is in place.
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

        # Phase 6.5a — doc-trust weight (source_type ranking). The field is an
        # ordinary review-grid field (Retrieval Ranking division, Task 1) —
        # interactive edits flow through the generic grid_edits/
        # _apply_review_edits path below, like every other config field. Only
        # an explicit --doc-weight flag bypasses the grid with a direct sparse
        # write (mirrors --reranking/--no-reranking above).
        if doc_weight is not None:
            _write_ranking_config(resolved_state_dir, doc_weight)

        # Write bind overrides into the config.yaml bind: section when the user
        # passed --host or --port. Absent these flags, the code defaults apply
        # (inherit from global config.yaml, then 127.0.0.1/8000-8100/auto_port).
        # We write sparse keys only — omitted keys inherit from global or code.
        if host is not None or port is not None:
            _apply_review_edits(
                resolved_state_dir,
                {
                    **({"bind.bind_host": host} if host is not None else {}),
                    **(
                        {
                            "bind.port_range_start": port,
                            "bind.auto_port": False,
                        }
                        if port is not None
                        else {}
                    ),
                },
            )

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

        # Resolve graphrag-extract answer for the fresh-init path. Passed into
        # apply_extract_engine below so extraction.mode is set by one writer that
        # considers BOTH session-extract and doc-graph-extract signals.
        _fresh_graphrag_ans = (
            enable_graphrag_extract
            if enable_graphrag_extract is not None
            else (graphrag_extract_ans if plan.confirm else None)
        )

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

        # Resolve + persist the extraction mode (subagent/off), and reconcile
        # Claude Code hooks. extraction.mode governs BOTH session summarization
        # and doc-graph triplet extraction — one writer, one key.
        # Apply when: fresh config written, session-extract flag explicit, OR
        # graphrag-extract question was answered.
        if (
            provider_config_written
            or enable_extract is not None
            or _fresh_graphrag_ans is not None
        ):
            extract_mode = apply_extract_engine(
                resolved_state_dir,
                project_root,
                plan.extract,
                graphrag_extract=bool(_fresh_graphrag_ans),
                graphrag_mode=graphrag_extract_mode,
            )
            if not json_output and extract_mode == "subagent":
                console.print(
                    "[dim]Session summarization: on (subagent — summarized only "
                    "inside Claude Code, free on your Claude Code subscription. "
                    "No server-side paid summarization).[/]"
                )

        # B5: ensure .brainpalace/ is git-ignored for the project.
        gitignore_added = ensure_gitignore_entry(project_root)

        # D12/D16: write BrainPalace's MCP server into .mcp.json (merged,
        # never clobbering other servers — A10). Runs on BOTH init paths,
        # including --defer-activation: .mcp.json is configuration, not
        # activation, so it starts no process and costs nothing until Claude
        # Code next boots. Fail-soft: a malformed existing .mcp.json must not
        # abort an otherwise-successful init; report it and move on.
        mcp_installed = False
        mcp_notice: str | None = None
        if enable_mcp:
            try:
                _mcp = install_mcp(project_root)
                mcp_installed = True
                mcp_notice = restart_notice(
                    changed=_mcp.changed, approved=_mcp.approved, scope=_mcp.scope
                )
                if _mcp.skip_reason and not json_output:
                    console.print(
                        f"[yellow]MCP approval skipped:[/] {_mcp.skip_reason}"
                    )
            except ValueError as e:
                if not json_output:
                    console.print(f"[yellow]MCP setup skipped:[/] {e}")

        # Apply the grid's sparse edit map — runs after the fresh config write so
        # any provider change is reflected in the cost shown by the estimate.
        # The grid (review_config) already ran at the top of the confirm block;
        # grid_edits = consent_edits ∪ field_edits collected there.  On non-
        # interactive / --yes paths grid_edits is never set, so this block is
        # skipped (plan.confirm is False on those paths).
        if plan.confirm and grid_edits:
            _apply_review_edits(resolved_state_dir, grid_edits)
            _reconcile_optional_deps(grid_edits)
            _validate_and_warn(resolved_state_dir / "config.yaml")

        # Pre-index token estimate — runs AFTER the review screen so the cost
        # reflects any provider edit the user just made (finding #12).
        # The config is fully written at this point.
        #
        # Interactive order: review → estimate (proceed/change/cancel) →
        # show the "init will:" summary → final Proceed.
        # A --yes run keeps a single estimate prompt and no extra confirmation.
        estimate_accepted = False
        if is_tty and plan.start:
            interactive_gate = plan.confirm  # non --yes run → offer skip + Proceed
            do_estimate = True
            if interactive_gate:
                do_estimate = click.confirm("Estimate token usage first?", default=True)
            if do_estimate:
                chosen = _estimate_and_confirm_local(
                    [Path(f) for f in folders] if folders else [project_root],
                    resolved_state_dir / "config.yaml",
                    include_code,
                    interactive=plan.confirm,
                    state_dir=resolved_state_dir,
                    project_root=project_root,
                )
                if chosen is None:
                    if created_brainpalace:
                        shutil.rmtree(resolved_state_dir, ignore_errors=True)
                        console.print("[dim]Cancelled — removed .brainpalace.[/]")
                    else:
                        console.print("[dim]Cancelled — kept existing .brainpalace.[/]")
                    return
                include_code = chosen
                estimate_accepted = True  # estimate shown AND user proceeded
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
                _gate_prompt = (
                    "Start the BrainPalace server now?"
                    if (plan.start and start is None)
                    else "Proceed?"
                )
                if not click.confirm(_gate_prompt, default=True):
                    plan = downgrade_to_config_only(plan)

        # Index DATA dirs are created only now — after the estimate was accepted
        # (or skipped for a non-interactive run) — so a cancel above leaves no
        # ChromaDB/BM25 scaffolding behind.
        (resolved_state_dir / "data").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "chroma_db").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "bm25_index").mkdir(exist_ok=True)
        (resolved_state_dir / "data" / "llamaindex").mkdir(exist_ok=True)

        post_init_steps = []

        # Build config dict for the result banner/JSON (yaml config, not bind dict).
        try:
            config: dict[str, object] = yaml.safe_load(config_path.read_text()) or {}
        except (OSError, Exception):
            config = {}

        # Arm the activation gate ONLY for a deferred (plugin) init of a project
        # that was never started (hardening item 5): re-running plugin init on an
        # already-activated project must NOT re-gate its autostart. "Never
        # activated" = absent from the durable known-projects fleet store (every
        # `brainpalace start` / dashboard Start records it there).
        armed_await_first_start = False
        if defer_activation_effective:
            try:
                from brainpalace_cli import known_projects
                from brainpalace_cli.config_schema import write_await_first_start

                never_started = (
                    str(project_root.resolve()) not in known_projects.load_existing()
                )
                if never_started:
                    write_await_first_start(resolved_state_dir, True)
                    armed_await_first_start = True
            except Exception:
                pass

        if plan.start:
            # extraction.mode auto/provider => the server distiller (not the
            # plugin subagent) will summarize+embed; those keys are genuinely
            # needed. Read AFTER the config writes above so this run's
            # just-persisted mode is seen.
            _extract_mode, _ = read_session_state(resolved_state_dir)
            _server_distill = _extract_mode not in ("off", "subagent")
            needs_embedding, needs_summarization = _provider_needs(
                plan, folders, server_distill=_server_distill
            )
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
                force_budget=estimate_accepted,
                needs_embedding=needs_embedding,
                needs_summarization=needs_summarization,
                folders=folders,
            )

        _emit_init_result(
            await_first_start=armed_await_first_start,
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
            folders=folders,
            mcp_installed=mcp_installed,
            mcp_notice=mcp_notice,
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

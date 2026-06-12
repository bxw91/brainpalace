"""Opt-in installation of optional server extras (D1/D2).

A feature whose enablement needs an optional dependency installs that dep ONLY
when the user opts into the feature at install/init time — never automatically
because the feature is default-ON in code. Each extra maps to a poetry extra on
the ``brainpalace-rag`` server package; we install ``brainpalace-rag[<extra>]``
into the SAME environment the CLI runs in, pinned to the resolved server
version, with the package-manager cache bypassed (consistent with the
install/update pin fix).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass

from brainpalace_cli.commands.update import detect_install_manager


@dataclass(frozen=True)
class OptionalExtra:
    extra: str  # poetry extra name on brainpalace-rag
    probe_module: str  # import name used to test "is it installed?"
    download_note: str  # one-line human warning shown before the prompt
    deps: tuple[str, ...]  # human-facing dep list (doctor display)


REGISTRY: dict[str, OptionalExtra] = {
    "graphrag": OptionalExtra(
        "graphrag",
        "langextract",
        "GraphRAG document extraction needs an extra download (langextract).",
        ("langextract",),
    ),
    "lemma-hr": OptionalExtra(
        "lemma-hr",
        "simplemma",
        "The 'lemma' BM25 engine needs an extra download (simplemma, ~65 MB).",
        ("simplemma",),
    ),
    "postgres": OptionalExtra(
        "postgres",
        "asyncpg",
        "The postgres storage backend needs extra downloads (asyncpg, sqlalchemy).",
        ("asyncpg", "sqlalchemy"),
    ),
    "reranker-local": OptionalExtra(
        "reranker-local",
        "sentence_transformers",
        "The local cross-encoder reranker is a LARGE download "
        "(sentence-transformers + PyTorch, ~2.8 GB).",
        ("sentence-transformers", "torch"),
    ),
}


@dataclass(frozen=True)
class EnsureResult:
    installed: bool
    printed: bool = False


def is_installed(extra: str) -> bool:
    """True when the extra's probe module is importable in this env."""
    spec_name = REGISTRY[extra].probe_module
    return importlib.util.find_spec(spec_name) is not None


def _installed_rag_version() -> str | None:
    """Resolved ``brainpalace-rag`` version, or None if it can't be read."""
    try:
        from importlib.metadata import version

        return version("brainpalace-rag")
    except Exception:
        return None


def _requirement(extra: str, version: str | None) -> str:
    pin = f"=={version}" if version else ""
    return f"brainpalace-rag[{extra}]{pin}"


def install_argv(extra: str, manager: str, version: str | None) -> list[str] | None:
    """Build the install command for ``brainpalace-rag[extra]`` per manager.

    Returns None for an unknown/unsupported manager (caller prints instead).
    """
    req = _requirement(extra, version)
    if manager == "pipx":
        return ["pipx", "inject", "brainpalace-cli", req, "--pip-args=--no-cache-dir"]
    if manager == "uv":
        # uv 0.11.x: `--with` adds + persists the extra in the tool receipt.
        return ["uv", "tool", "install", "brainpalace-cli", "--with", req, "--no-cache"]
    if manager == "pip":
        return [sys.executable, "-m", "pip", "install", "--no-cache-dir", req]
    return None


def manual_install_hint(extra: str) -> str:
    """A single-line, manager-aware hint for installing ``extra`` manually.

    Reuses the detected install manager + ``install_argv`` so the suggested
    command matches how the CLI was installed (pipx/uv/pip). Falls back to the
    pipx-or-pip text when no manager can be detected.
    """
    version = _installed_rag_version()
    req = _requirement(extra, version)
    manager = detect_install_manager()
    argv = install_argv(extra, manager, version) if manager else None
    if argv is None:
        return f"pipx inject brainpalace-cli '{req}'  # or: pip install '{req}'"
    return " ".join(argv)


def _print_manual(extra: str, version: str | None) -> None:
    req = _requirement(extra, version)
    print(
        f"  To enable this later, install the extra into the brainpalace "
        f"environment:\n    pipx inject brainpalace-cli '{req}'\n"
        f"    # or: pip install '{req}'"
    )


def ensure_extra(extra: str, *, assume_yes: bool) -> EnsureResult:
    """Install the extra if missing. Never raises.

    Already present -> no-op. Manager undetected / run failure -> print the exact
    command and return installed=False. ``assume_yes`` is reserved for callers
    that have already collected consent (all current callers pass True after the
    feature prompt).
    """
    if extra not in REGISTRY:
        return EnsureResult(installed=False)
    if is_installed(extra):
        return EnsureResult(installed=True)
    manager = detect_install_manager()
    version = _installed_rag_version()
    argv = install_argv(extra, manager, version) if manager else None
    if argv is None:
        _print_manual(extra, version)
        return EnsureResult(installed=False, printed=True)
    print(f"  Installing optional extra '{extra}' ({' '.join(REGISTRY[extra].deps)})…")
    try:
        # Stream the package manager's output straight to the user's terminal so
        # they see download/build progress (this can take a while for langextract).
        result = subprocess.run(argv)
    except OSError:
        _print_manual(extra, version)
        return EnsureResult(installed=False, printed=True)
    if result.returncode == 0 and is_installed(extra):
        return EnsureResult(installed=True)
    _print_manual(extra, version)
    return EnsureResult(installed=False, printed=True)

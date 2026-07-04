"""`brainpalace lsp` — manage LSP language servers."""

from __future__ import annotations

import sys

import click

from brainpalace_cli.lsp_install import EnsureResult, ensure_server


@click.group(name="lsp")
def lsp_group() -> None:
    """Manage LSP language servers used for exact cross-file graph edges."""


@lsp_group.command(name="install")
@click.option(
    "--lang", default="python", show_default=True, help="Language server to install."
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Install without prompting (CI-safe).",
)
def install_command(lang: str, assume_yes: bool) -> None:
    """Install the language server for LANG (Python -> pyright)."""
    result = ensure_server(lang, assume_yes=assume_yes, interactive=sys.stdin.isatty())
    if result is EnsureResult.ALREADY_PRESENT:
        click.echo(f"Language server for {lang} is already installed.")
    elif result is EnsureResult.DECLINED:
        click.echo("Skipped.")
    elif result in (EnsureResult.FAILED, EnsureResult.NO_MANAGER):
        raise SystemExit(1)
    # INSTALLED / INSTALLED_NOT_ON_PATH already echoed by ensure_server (both exit 0;
    # not-on-PATH is a successful install the user must add to PATH, not a failure).

"""``brainpalace doctor`` — diagnose installation, configuration and server state."""

from __future__ import annotations

import json
import sys
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from brainpalace_cli.diagnostics import (
    SEVERITY_FAIL,
    SEVERITY_OK,
    SEVERITY_WARN,
    apply_safe_fixes,
    load_project_config_dict,
    report_to_json,
    run_doctor,
)
from brainpalace_cli.lsp_install import EnsureResult, ensure_server

console = Console()


def _lsp_missing_languages() -> list[str]:
    """Languages toggled on in graph_indexing.lsp whose server binary is absent.

    Fail-soft: the CLI consumes the server as a versioned wheel, which may
    predate the ``configured_languages``/``detect_servers`` API — an older (or
    unimportable) server yields an empty list rather than crashing doctor."""
    try:
        from brainpalace_server.lsp import servers

        return sorted(servers.configured_languages() - servers.detect_servers())
    except Exception:  # noqa: BLE001 — server missing or too old: skip the offer
        return []


def extras_status_lines(config: dict[str, Any]) -> list[str]:
    """One status line per ENABLED dep-bearing feature whose extra is checked.

    Enabled but missing -> a 'missing' line with the fix command. Declined
    features (engine=stem, backend!=postgres) are omitted
    (D2: a declined feature must not nag).
    """
    from brainpalace_cli import optional_deps as od

    def _section(name: str) -> dict[str, Any]:
        block = config.get(name)
        return block if isinstance(block, dict) else {}

    enabled: list[str] = []
    if _section("bm25").get("engine") == "lemma":
        enabled.append("lemma-hr")
    if _section("storage").get("backend") == "postgres":
        enabled.append("postgres")

    lines: list[str] = []
    for extra in enabled:
        if od.is_installed(extra):
            lines.append(f"  extra '{extra}': installed")
        else:
            hint = od.manual_install_hint(extra)
            lines.append(f"  extra '{extra}': MISSING — install: {hint}")
    return lines


_STATUS_STYLE = {
    SEVERITY_OK: ("green", "OK"),
    SEVERITY_WARN: ("yellow", "WARN"),
    SEVERITY_FAIL: ("red", "FAIL"),
}


@click.command("doctor")
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="Server URL to probe (default: resolved from runtime.json or config).",
)
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
@click.option(
    "--fix",
    "apply_fixes",
    is_flag=True,
    help=(
        "Apply safe, idempotent, offline fixes (add .brainpalace/ to .gitignore, "
        "create state dir + stub config.yaml). Will not touch API keys, network, "
        "or user code. Re-runs the report after fixing."
    ),
)
@click.option(
    "--reap",
    "reap",
    is_flag=True,
    help=(
        "Kill orphan server processes not referenced by a live registry entry "
        "(leaked servers that hold ports). Runs before the diagnostics."
    ),
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Auto-install missing LSP servers without prompting.",
)
def doctor_command(
    url: str | None,
    json_output: bool,
    apply_fixes: bool,
    reap: bool,
    assume_yes: bool,
) -> None:
    """Diagnose your BrainPalace setup.

    Inspects Python version, project init state, provider config, required
    API keys, optional dependencies, .gitignore hygiene, and whether the
    server is reachable. Exits non-zero on any critical failure so it can
    be used in scripts (``brainpalace doctor || brainpalace init``).

    Pass ``--fix`` to auto-apply the safe subset of remediations and re-run.
    Pass ``--reap`` to first kill orphan (unreferenced) server processes.
    """
    reaped: list[int] = []
    survived: list[int] = []
    if reap:
        from brainpalace_cli.commands.reap import reap_orphans

        outcome = reap_orphans()
        reaped, survived = outcome.reaped, outcome.survived
        if not json_output:
            if reaped:
                console.print(
                    f"[green]Reaped {len(reaped)} orphan server process(es):[/] "
                    f"{', '.join(map(str, reaped))}"
                )
            else:
                console.print("[dim]No orphan server processes found.[/]")
            if survived:
                console.print(
                    f"[red]Still alive after SIGKILL:[/] "
                    f"{', '.join(map(str, survived))}"
                )

    report = run_doctor(server_url_override=url)

    fix_actions: list[str] = []
    if apply_fixes:
        fix_actions = apply_safe_fixes(report)
        if fix_actions:
            # Re-run so the printed report reflects the fixed state.
            report = run_doctor(server_url_override=url)

    if json_output:
        payload = json.loads(report_to_json(report))
        if apply_fixes:
            payload["applied_fixes"] = fix_actions
        if reap:
            payload["reaped_pids"] = reaped
            payload["surviving_pids"] = survived
        click.echo(json.dumps(payload, indent=2))
        raise SystemExit(report.exit_code)

    header_color = "green" if report.exit_code == 0 else "red"
    console.print(
        Panel(
            (
                f"[bold]Project root:[/] {report.project_root}\n"
                f"[bold]State dir:[/]    {report.state_dir} "
                f"({'present' if report.state_dir_exists else 'missing'})\n"
                f"[bold]Server URL:[/]   {report.server_url}"
            ),
            title="BrainPalace Doctor",
            border_style=header_color,
        )
    )

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Check", style="dim")
    table.add_column("Status")
    table.add_column("Details", overflow="fold")

    for check in report.checks:
        style, label = _STATUS_STYLE.get(check.status, ("white", check.status.upper()))
        body = check.message
        if check.fix:
            body = f"{body}\n[dim]→ {check.fix}[/]"
        table.add_row(check.name, f"[{style}]{label}[/]", body)

    console.print(table)

    from pathlib import Path

    extras_lines = extras_status_lines(load_project_config_dict(Path(report.state_dir)))
    if extras_lines:
        console.print("\n[cyan]Optional extras:[/]")
        for line in extras_lines:
            console.print(line)

    if apply_fixes:
        if fix_actions:
            console.print("\n[cyan]Applied safe fixes:[/]")
            for action in fix_actions:
                console.print(f"  • {action}")
        else:
            console.print(
                "\n[dim]No safe fixes applied (nothing actionable, or all "
                "checks already passing).[/]"
            )

    # LSP: offer to install a configured-but-missing language server. Unlike
    # init, doctor MAY auto-install on --yes (explicit diagnostic-repair intent).
    missing = _lsp_missing_languages()
    if missing:
        console.print("\n[cyan]LSP language servers:[/]")
        for lang in missing:
            result = ensure_server(
                lang, assume_yes=assume_yes, interactive=sys.stdin.isatty()
            )
            if result is EnsureResult.FAILED:
                console.print(f"  LSP: {lang} server install failed.")

    if report.exit_code != 0:
        console.print(
            "\n[red]Doctor reported critical issues.[/] "
            "Fix the items above and re-run.",
        )
    else:
        console.print("\n[green]All critical checks passed.[/]")

    raise SystemExit(report.exit_code)

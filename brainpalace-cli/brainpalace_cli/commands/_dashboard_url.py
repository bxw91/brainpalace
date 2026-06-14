"""Single renderer for the web-dashboard URL (used by init/start/dashboard)."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel

_console = Console()


def render_dashboard_url(
    dash: dict[str, Any] | None, *, console: Console | None = None
) -> None:
    """Print the clickable dashboard URL in the standard hot_pink panel.

    No-op when ``dash`` is None/empty. Browser-opening stays with the caller.
    """
    if not dash or not dash.get("base_url"):
        return
    out = console or _console
    url = dash["base_url"]
    verb = "started" if dash.get("started") else "running"
    out.print(
        Panel(
            f"[bold][link={url}]{url}[/link][/]",
            title=f"Web Dashboard ({verb})",
            border_style="hot_pink",
        )
    )


def dashboard_status_info() -> dict[str, Any]:
    """Best-effort dashboard status probe (does NOT start it).

    Returns the ``dashboard_status()`` dict, or ``{}`` when the dashboard package
    isn't installed or the probe fails.
    """
    try:
        from brainpalace_dashboard import server as _dash
    except ImportError:
        return {}
    try:
        return dict(_dash.dashboard_status() or {})
    except Exception:
        return {}


def render_dashboard_status(console: Console | None = None) -> None:
    """Always print the pink dashboard box for ``brainpalace status``.

    Shows a clickable URL when running, or a clear notice when the dashboard is
    stopped or not installed — so the box is present either way.
    """
    out = console or _console
    try:
        import brainpalace_dashboard  # noqa: F401
    except ImportError:
        out.print(
            Panel(
                "[dim]not installed[/] — ships on Python 3.12+ "
                "([bold]pip install brainpalace-dashboard[/])",
                title="Web Dashboard",
                border_style="hot_pink",
            )
        )
        return
    info = dashboard_status_info()
    if info.get("status") == "running":
        url = info.get("base_url") or ""
        health = "[green]healthy[/]" if info.get("healthy") else "[red]unhealthy[/]"
        body = (
            f"[bold][link={url}]{url}[/link][/]\n"
            f"Status: [green]running[/] ({health})"
        )
        port = info.get("port")
        if port:
            body += f"  ·  port {port}"
    else:
        body = (
            "[yellow]not running[/]\n" "Start it: [bold]brainpalace dashboard start[/]"
        )
    out.print(Panel(body, title="Web Dashboard", border_style="hot_pink"))

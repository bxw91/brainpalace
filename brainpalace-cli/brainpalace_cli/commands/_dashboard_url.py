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

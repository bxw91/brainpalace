from rich.console import Console

from brainpalace_cli.commands._dashboard_url import render_dashboard_url


def test_renders_hot_pink_panel_with_link():
    console = Console(record=True, width=80)
    render_dashboard_url(
        {"base_url": "http://127.0.0.1:8787/dashboard/", "started": False},
        console=console,
    )
    text = console.export_text()
    assert "127.0.0.1:8787/dashboard" in text
    # panel title present
    assert "Dashboard" in text


def test_noop_when_no_url():
    console = Console(record=True, width=80)
    render_dashboard_url(None, console=console)
    assert console.export_text().strip() == ""

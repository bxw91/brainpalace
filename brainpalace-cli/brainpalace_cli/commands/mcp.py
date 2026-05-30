"""mcp command — serve BrainPalace over the Model Context Protocol (stdio).

For use by MCP-aware AI clients (VS Code / GitHub Copilot agent mode,
Cursor, Kilo Code, Cline, Continue, Zed). Claude Code users typically
prefer the skill + slash commands installed by the plugin.

See ``docs/MCP_SETUP.md`` for per-client config snippets.
"""

import click


@click.command("mcp")
@click.option(
    "--ensure-server",
    is_flag=True,
    default=False,
    help=(
        "If no BrainPalace HTTP server is live for the spawn-time CWD "
        "project, start one before serving MCP. Recommended for every "
        "non-Claude-Code client (see Phase Q Task 5.5)."
    ),
)
def mcp_command(ensure_server: bool) -> None:
    """Start an MCP server over stdio.

    The MCP shim is a thin wrapper around the existing BrainPalace HTTP
    server's REST endpoints. The HTTP server must already be running for
    tool calls to succeed — pass ``--ensure-server`` to have the shim
    start it on boot if discovery finds none.
    """
    from brainpalace_cli.mcp_server.server import run_stdio

    run_stdio(ensure_server=ensure_server)

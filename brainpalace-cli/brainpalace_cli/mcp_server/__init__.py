"""MCP (Model Context Protocol) server for BrainPalace.

Opt-in stdio MCP shim — a thin wrapper over the existing HTTP server's
REST endpoints. NOT auto-mounted by the plugin manifest. Entry point is
``brainpalace mcp`` (see ``brainpalace_cli.cli``). For per-client setup
see ``docs/MCP_SETUP.md``.
"""

from __future__ import annotations

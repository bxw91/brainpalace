"""Main CLI entry point for brainpalace CLI.

This module provides the command-line interface for managing and querying
the BrainPalace RAG server.
"""

import click

from brainpalace_cli.commands.read_only import read_only_command

from . import version_display
from .commands import (
    ai_guide_command,
    backfill_command,
    cache_group,
    config_group,
    context_command,
    dashboard_command,
    doctor_command,
    dump_interface_command,
    extraction_group,
    folders_group,
    hook_group,
    index_command,
    ingest_command,
    init_command,
    inject_command,
    install_agent_command,
    install_session_hooks_command,
    jobs_command,
    list_command,
    lsp_group,
    mcp_command,
    memories_group,
    plugin_group,
    query_command,
    recall_command,
    records_group,
    references_group,
    remember_command,
    reset_command,
    rules_group,
    session_path_command,
    start_command,
    status_command,
    stop_command,
    submit_session_command,
    sync_docs_command,
    types_group,
    uninstall_command,
    update_command,
    verify_docs_command,
    whoami_command,
)
from .commands.entities import entities_group
from .commands.graph import graph_group


@click.group()
@click.version_option(version=version_display(), prog_name="brainpalace")
def cli() -> None:
    """BrainPalace CLI - Manage and query the BrainPalace RAG server.

    A command-line interface for interacting with the BrainPalace document
    indexing and semantic search API.

    \b
    Project Commands:
      init     Initialize a new brainpalace project
      start    Start the server for this project
      stop     Stop the server for this project
      list     List all running brainpalace instances
      dashboard  Launch the web control-plane dashboard

    \b
    Server Commands:
      status   Check server status
      query    Search documents
      ai-guide Print AI usage guidance (search rules, modes); for AI agents
      index    Index documents from a folder
      inject   Index documents with content injection
      jobs     View and manage job queue
      reset    Clear all indexed documents

    \b
    Cache Commands:
      cache    Manage the embedding cache (status, clear)

    \b
    Folder Commands:
      folders  Manage indexed folders (list, add, remove)

    \b
    File Type Commands:
      types    List available file type presets

    \b
    MCP (Model Context Protocol):
      mcp      Serve BrainPalace over stdio for MCP-aware AI clients

    \b
    Examples:
      brainpalace init                                # Initialize project
      brainpalace start                               # Start server
      brainpalace status                              # Check server status
      brainpalace query "how to use python"           # Search documents
      brainpalace index ./docs                        # Index documents
      brainpalace index ./src --include-type python   # Index with preset
      brainpalace inject --script enrich.py ./docs   # Index with injection
      brainpalace folders list                        # List indexed folders
      brainpalace folders remove ./docs --yes         # Remove folder chunks
      brainpalace types list                          # Show file type presets
      brainpalace stop                                # Stop server

    \b
    Environment Variables:
      BRAINPALACE_URL  Server URL (default: http://127.0.0.1:8000)
    """
    pass


# Register project management commands
cli.add_command(init_command, name="init")
cli.add_command(start_command, name="start")
cli.add_command(stop_command, name="stop")
cli.add_command(list_command, name="list")
cli.add_command(dashboard_command, name="dashboard")
cli.add_command(whoami_command, name="whoami")

# Register server interaction commands
cli.add_command(doctor_command, name="doctor")
cli.add_command(lsp_group, name="lsp")
cli.add_command(status_command, name="status")
cli.add_command(query_command, name="query")
cli.add_command(ai_guide_command, name="ai-guide")
cli.add_command(hook_group, name="hook")
cli.add_command(remember_command, name="remember")
cli.add_command(recall_command, name="recall")
cli.add_command(memories_group, name="memories")
cli.add_command(context_command, name="context")
cli.add_command(submit_session_command, name="submit-session")
cli.add_command(session_path_command, name="session-path")
cli.add_command(index_command, name="index")
cli.add_command(ingest_command, name="ingest")
cli.add_command(inject_command, name="inject")
cli.add_command(jobs_command, name="jobs")
cli.add_command(reset_command, name="reset")
cli.add_command(config_group, name="config")
cli.add_command(read_only_command, name="read-only")
cli.add_command(plugin_group, name="plugin")
cli.add_command(folders_group, name="folders")
cli.add_command(types_group, name="types")
cli.add_command(cache_group, name="cache")
cli.add_command(uninstall_command, name="uninstall")
cli.add_command(update_command, name="update")
cli.add_command(install_agent_command, name="install-agent")
cli.add_command(install_session_hooks_command, name="install-session-hooks")
cli.add_command(backfill_command, name="backfill-sessions")
cli.add_command(records_group, name="records")
cli.add_command(references_group, name="references")
cli.add_command(rules_group, name="rules")
cli.add_command(extraction_group, name="extraction")
cli.add_command(graph_group, name="graph")
cli.add_command(entities_group, name="entities")

# Register doc-sync maintenance commands (hidden; deterministic, never call an LLM)
cli.add_command(sync_docs_command, name="sync-docs")
cli.add_command(dump_interface_command, name="dump-interface")
cli.add_command(verify_docs_command, name="verify-docs")

# Register MCP server (opt-in stdio shim for non-Claude-Code AI clients)
cli.add_command(mcp_command, name="mcp")


if __name__ == "__main__":
    cli()

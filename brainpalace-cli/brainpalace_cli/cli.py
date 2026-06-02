"""Main CLI entry point for brainpalace CLI.

This module provides the command-line interface for managing and querying
the BrainPalace RAG server.
"""

import click

from . import __version__
from .commands import (
    cache_group,
    config_group,
    context_command,
    doctor_command,
    folders_group,
    index_command,
    init_command,
    inject_command,
    install_agent_command,
    jobs_command,
    list_command,
    mcp_command,
    memories_group,
    query_command,
    recall_command,
    remember_command,
    reset_command,
    start_command,
    status_command,
    stop_command,
    submit_session_command,
    types_group,
    uninstall_command,
    update_command,
    whoami_command,
)


@click.group()
@click.version_option(version=__version__, prog_name="brainpalace")
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

    \b
    Server Commands:
      status   Check server status
      query    Search documents
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
cli.add_command(whoami_command, name="whoami")

# Register server interaction commands
cli.add_command(doctor_command, name="doctor")
cli.add_command(status_command, name="status")
cli.add_command(query_command, name="query")
cli.add_command(remember_command, name="remember")
cli.add_command(recall_command, name="recall")
cli.add_command(memories_group, name="memories")
cli.add_command(context_command, name="context")
cli.add_command(submit_session_command, name="submit-session")
cli.add_command(index_command, name="index")
cli.add_command(inject_command, name="inject")
cli.add_command(jobs_command, name="jobs")
cli.add_command(reset_command, name="reset")
cli.add_command(config_group, name="config")
cli.add_command(folders_group, name="folders")
cli.add_command(types_group, name="types")
cli.add_command(cache_group, name="cache")
cli.add_command(uninstall_command, name="uninstall")
cli.add_command(update_command, name="update")
cli.add_command(install_agent_command, name="install-agent")

# Register MCP server (opt-in stdio shim for non-Claude-Code AI clients)
cli.add_command(mcp_command, name="mcp")


if __name__ == "__main__":
    cli()

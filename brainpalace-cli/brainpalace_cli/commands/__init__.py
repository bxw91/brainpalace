"""CLI commands for brainpalace."""

from .ai_guide import ai_guide_command
from .backfill import backfill_command
from .cache import cache_group
from .config import config_group
from .context import context_command
from .dashboard import dashboard_command
from .doctor import doctor_command
from .extraction import extraction_group
from .folders import folders_group
from .hook import hook_group
from .index import index_command
from .ingest import ingest_command
from .init import init_command
from .inject import inject_command
from .install_agent import install_agent_command
from .jobs import jobs_command
from .list_cmd import list_command
from .lsp import lsp_group
from .mcp import mcp_command
from .memories import memories_group
from .plugin_detect import plugin_group
from .query import query_command
from .recall import recall_command
from .records import records_group
from .references import references_group
from .remember import remember_command
from .reset import reset_command
from .rules import rules_group
from .session_hooks import install_session_hooks_command
from .sessions import session_path_command, submit_session_command
from .start import start_command
from .status import status_command
from .stop import stop_command
from .sync_docs import dump_interface_command, sync_docs_command
from .types import types_group
from .uninstall import uninstall_command
from .update import update_command
from .verify_docs import verify_docs_command
from .whoami import whoami_command

__all__ = [
    "backfill_command",
    "extraction_group",
    "cache_group",
    "config_group",
    "context_command",
    "dashboard_command",
    "doctor_command",
    "folders_group",
    "index_command",
    "ingest_command",
    "inject_command",
    "init_command",
    "install_agent_command",
    "install_session_hooks_command",
    "jobs_command",
    "list_command",
    "lsp_group",
    "mcp_command",
    "memories_group",
    "plugin_group",
    "ai_guide_command",
    "hook_group",
    "query_command",
    "records_group",
    "references_group",
    "recall_command",
    "remember_command",
    "reset_command",
    "rules_group",
    "session_path_command",
    "start_command",
    "submit_session_command",
    "status_command",
    "stop_command",
    "dump_interface_command",
    "sync_docs_command",
    "verify_docs_command",
    "types_group",
    "uninstall_command",
    "update_command",
    "whoami_command",
]

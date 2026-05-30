"""CLI commands for brainpalace."""

from .cache import cache_group
from .config import config_group
from .context import context_command
from .doctor import doctor_command
from .folders import folders_group
from .index import index_command
from .init import init_command
from .inject import inject_command
from .install_agent import install_agent_command
from .jobs import jobs_command
from .list_cmd import list_command
from .mcp import mcp_command
from .memories import memories_group
from .query import query_command
from .recall import recall_command
from .remember import remember_command
from .reset import reset_command
from .sessions import submit_session_command
from .start import start_command
from .status import status_command
from .stop import stop_command
from .types import types_group
from .uninstall import uninstall_command
from .whoami import whoami_command

__all__ = [
    "cache_group",
    "config_group",
    "context_command",
    "doctor_command",
    "folders_group",
    "index_command",
    "inject_command",
    "init_command",
    "install_agent_command",
    "jobs_command",
    "list_command",
    "mcp_command",
    "memories_group",
    "query_command",
    "recall_command",
    "remember_command",
    "reset_command",
    "start_command",
    "submit_session_command",
    "status_command",
    "stop_command",
    "types_group",
    "uninstall_command",
    "whoami_command",
]

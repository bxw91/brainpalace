"""HTTP client for communicating with BrainPalace server."""

from .api_client import (
    ConnectionError,
    DocServeClient,
    DocServeError,
    FolderInfo,
    ServerError,
)
from .errors import EXIT_CODE_CONNECTION_ERROR, exit_on_connection_error

__all__ = [
    "DocServeClient",
    "DocServeError",
    "ConnectionError",
    "EXIT_CODE_CONNECTION_ERROR",
    "FolderInfo",
    "ServerError",
    "exit_on_connection_error",
]

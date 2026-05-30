"""PostgreSQL storage backend with pgvector and tsvector.

This package provides the PostgreSQL implementation of the
StorageBackendProtocol using pgvector for vector search and
tsvector for full-text keyword search.
"""

from brainpalace_server.storage.postgres.backend import PostgresBackend
from brainpalace_server.storage.postgres.config import PostgresConfig
from brainpalace_server.storage.postgres.connection import (
    PostgresConnectionManager,
)
from brainpalace_server.storage.postgres.schema import (
    PostgresSchemaManager,
)

__all__ = [
    "PostgresBackend",
    "PostgresConfig",
    "PostgresConnectionManager",
    "PostgresSchemaManager",
]

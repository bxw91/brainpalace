"""API routers for different endpoint groups."""

from .cache import router as cache_router
from .folders import router as folders_router
from .health import router as health_router
from .index import router as index_router
from .ingest import router as ingest_router
from .jobs import router as jobs_router
from .metrics import router as metrics_router
from .query import router as query_router
from .records import router as records_router
from .rules import router as rules_router
from .runtime import router as runtime_router

__all__ = [
    "cache_router",
    "folders_router",
    "health_router",
    "index_router",
    "ingest_router",
    "jobs_router",
    "metrics_router",
    "query_router",
    "records_router",
    "rules_router",
    "runtime_router",
]

"""Pydantic input schemas for BrainPalace MCP tools.

Each tool's input is described by a model here; the model is also the
source of truth for the JSON schema MCP clients see during ``list_tools``.
Descriptions are intentionally terse — every byte ships in the client's
context (see the "tool description context cost" risk in the Phase Q plan).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QueryMode = Literal["bm25", "vector", "hybrid", "graph", "multi"]

# Shared: override CWD-based server discovery. See the CWD-coupling risk
# in the Phase Q plan — the long-lived stdio MCP process is pinned to its
# spawn-time CWD, so callers may pass ``path`` to target a different project.
_PATH_DESC = "Resolve the server owning this path instead of the MCP process CWD"


class QueryInput(BaseModel):
    query: str = Field(..., description="Search query text")
    mode: QueryMode = Field(default="hybrid", description="Search mode")
    top_k: int = Field(default=8, ge=1, le=100)
    languages: list[str] | None = None
    source_types: list[str] | None = None
    language: str | None = Field(
        default=None,
        description=(
            "BM25 query language override; defaults to project bm25.language. "
            "ISO 639-1 code (e.g. 'en', 'de', 'hr'). Only affects BM25 tokenization."
        ),
    )
    path: str | None = Field(default=None, description=_PATH_DESC)


class WhoamiInput(BaseModel):
    file_path: str | None = None


class StatusInput(BaseModel):
    path: str | None = Field(default=None, description=_PATH_DESC)


class FoldersListInput(BaseModel):
    path: str | None = Field(default=None, description=_PATH_DESC)


class JobsListInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    path: str | None = Field(default=None, description=_PATH_DESC)


class MemorizeInput(BaseModel):
    text: str = Field(..., description="The durable fact to remember")
    section: str = Field(default="Notes", description="Markdown section")
    tags: list[str] | None = None
    path: str | None = Field(default=None, description=_PATH_DESC)


class RecallInput(BaseModel):
    query: str = Field(..., description="Recall query (memory namespace only)")
    top_k: int = Field(default=5, ge=1, le=50)
    path: str | None = Field(default=None, description=_PATH_DESC)


class SessionContextInput(BaseModel):
    path: str | None = Field(default=None, description=_PATH_DESC)

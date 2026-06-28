"""The ``server:`` config section — server-level operational switches.

Currently just ``read_only`` (query-only mode). Modeled so it auto-renders as a
toggle in the dashboard Config tab and the ``brainpalace init`` review grid, like
every other model-backed section. The live read path stays
``runtime_mode.is_read_only`` (env wins over this config key)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    read_only: bool = Field(
        default=False,
        description=(
            "Query-only mode: the server answers searches but performs no "
            "embedding, summarization, or index writes. Env BRAINPALACE_READ_ONLY "
            "overrides this."
        ),
    )

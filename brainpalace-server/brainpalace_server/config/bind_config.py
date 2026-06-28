"""Per-project ``bind:`` config — the runtime bind the server uses at start.

Replaces the legacy ``config.json`` bind file; resolved project→global by the
shared YAML merge (``load_raw_config``)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import load_raw_config


class BindConfig(BaseModel):
    bind_host: str = Field(
        default="127.0.0.1", description="Host/IP the server binds to."
    )
    port_range_start: int = Field(
        default=8000, ge=1, le=65535, description="First port tried."
    )
    port_range_end: int = Field(
        default=8100, ge=1, le=65535, description="Last port tried."
    )
    auto_port: bool = Field(
        default=True, description="Pick the first free port in the range."
    )


def load_bind_config(config_path: Path | None = None) -> BindConfig:
    try:
        raw = load_raw_config(config_path)
        block = raw.get("bind") if isinstance(raw, dict) else None
    except (OSError, yaml.YAMLError, ValueError):
        block = None
    if not isinstance(block, dict):
        return BindConfig()
    fields = {k: v for k, v in block.items() if k in BindConfig.model_fields}
    try:
        return BindConfig(**fields)
    except ValueError:
        return BindConfig()

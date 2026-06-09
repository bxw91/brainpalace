"""Per-project bm25: config block (language pipeline)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import load_raw_config


class BM25Config(BaseModel):
    language: str = "en"  # project default NL language
    engine: Literal["stem", "lemma"] = "stem"
    detect: bool = False  # per-document detection, opt-in
    detect_min_confidence: float = Field(0.6, ge=0.0, le=1.0)


def load_bm25_config(path: Path | None = None) -> BM25Config:
    data = load_raw_config(path)
    return BM25Config(**(data.get("bm25") or {}))

"""Per-project bm25: config block (language pipeline)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import _find_config_file


class BM25Config(BaseModel):
    language: str = "en"  # project default NL language
    engine: Literal["stem", "lemma"] = "stem"
    detect: bool = False  # per-document detection, opt-in
    detect_min_confidence: float = Field(0.6, ge=0.0, le=1.0)


def load_bm25_config(path: Path | None = None) -> BM25Config:
    path = path or _find_config_file()
    if path is None or not Path(path).exists():
        return BM25Config()
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return BM25Config(**(data.get("bm25") or {}))

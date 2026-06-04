"""Shared helpers for reading/writing the project BM25 config block.

This module is imported by both ``init.py`` and ``folders.py`` so that the
deep-merge logic for ``bm25.language`` / ``bm25.engine`` in
``.brainpalace/config.yaml`` lives in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def set_project_bm25(
    state_dir: Path,
    *,
    language: str | None = None,
    engine: str | None = None,
) -> None:
    """Deep-merge BM25 settings into the project config.yaml.

    Only the keys explicitly passed (non-None) are updated; all other keys
    in the existing config are preserved.  Idempotent.

    The server's ``load_bm25_config()`` reads ``bm25.language`` and
    ``bm25.engine`` from this file at startup.

    Args:
        state_dir: Path to ``.brainpalace/`` directory.
        language: ISO 639-1 language code to set as ``bm25.language``.
                  ``None`` → leave existing value unchanged.
        engine: BM25 tokenisation engine (``"stem"`` or ``"lemma"``).
                ``None`` → leave existing value unchanged.
    """
    config_path = state_dir / "config.yaml"
    data: dict[str, object] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text()) or {}
        if isinstance(loaded, dict):
            data = loaded

    bm25_block = data.get("bm25")
    if not isinstance(bm25_block, dict):
        bm25_block = {}

    if language is not None:
        bm25_block["language"] = language
    if engine is not None:
        bm25_block["engine"] = engine

    data["bm25"] = bm25_block
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

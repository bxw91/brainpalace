"""Tests for the server-less, in-process token estimate (services.estimate)."""

import asyncio
from pathlib import Path

import pytest


def test_estimate_local_counts_documents(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "README.md").write_text("# hello\nsome docs\n")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("embedding:\n  provider: openai\n  model: text-embedding-3-large\n")

    from brainpalace_server.services.estimate import estimate_tokens_local

    est = asyncio.run(
        estimate_tokens_local(str(tmp_path), include_code=True, config_path=str(cfg))
    )
    assert est["files"] >= 2
    assert est["est_embedding_tokens"] > 0


@pytest.mark.asyncio
async def test_by_folder_breakdown(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def a():\n    return 1\n" * 20)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "b.md").write_text("# title\n\nbody text here\n" * 20)
    (tmp_path / "root.md").write_text("# root\n\nloose file\n" * 20)

    from brainpalace_server.services.estimate import estimate_tokens_local

    est = await estimate_tokens_local(str(tmp_path), include_code=True)

    by = {row["name"]: row for row in est["by_folder"]}
    assert set(by) == {"pkg", "docs", "(root files)"}
    assert by["pkg"]["code_tokens"] > 0 and by["pkg"]["doc_tokens"] == 0
    assert by["docs"]["doc_tokens"] > 0 and by["docs"]["code_tokens"] == 0
    assert by["(root files)"]["files"] == 1
    # per-folder file counts sum to the top-level total
    assert sum(r["files"] for r in est["by_folder"]) == est["files"]

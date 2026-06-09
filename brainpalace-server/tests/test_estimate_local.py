"""Tests for the server-less, in-process token estimate (services.estimate)."""

import asyncio


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

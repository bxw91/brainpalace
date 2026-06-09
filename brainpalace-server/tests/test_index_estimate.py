"""Tests for the dry-run embedding-token estimate (IndexingService.estimate_tokens)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brainpalace_server.indexing.document_loader import LoadedDocument
from brainpalace_server.models import IndexRequest
from brainpalace_server.services import IndexingService


def _doc(text: str, source_type: str) -> LoadedDocument:
    return LoadedDocument(
        text=text,
        source="s",
        file_name="f",
        file_path="/p/f",
        file_size=len(text.encode()),
        metadata={"source_type": source_type},
    )


def _service(docs: list[LoadedDocument]) -> IndexingService:
    loader = MagicMock()
    loader.load_files = AsyncMock(return_value=docs)
    # storage_backend mock avoids the get_storage_backend() factory; estimate
    # never touches storage anyway.
    return IndexingService(document_loader=loader, storage_backend=MagicMock())


# ---------------------------------------------------------------------------
# Git-repo helper (inline — no importable monorepo fixture exists)
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo with 2 commits for estimate tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev Person")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "add README")
    (repo / "main.py").write_text("print('hi')\n")
    _git(repo, "add", "main.py")
    _git(repo, "commit", "-m", "add main")
    return repo


def _provider(provider: str, model: str) -> MagicMock:
    settings = MagicMock()
    settings.embedding.provider = provider
    settings.embedding.model = model
    return settings


def _no_git():
    """Patch load_git_indexing_config to return disabled config (unit-test isolation).

    Patched at the source module because estimate_tokens uses a local import.
    """
    from brainpalace_server.config.git_config import GitIndexingConfig

    return patch(
        "brainpalace_server.config.git_config.load_git_indexing_config",
        return_value=GitIndexingConfig(enabled=False),
    )


def _no_sessions():
    """Patch load_session_indexing_config to return a disabled config (isolation).

    Patched at the source module because estimate_tokens uses a local import.
    """
    from brainpalace_server.config.session_config import SessionIndexingConfig

    return patch(
        "brainpalace_server.config.session_config.load_session_indexing_config",
        return_value=SessionIndexingConfig(enabled=False),
    )


@pytest.mark.asyncio
async def test_estimate_heuristic_split_and_overlap() -> None:
    svc = _service([_doc("a" * 400, "code"), _doc("b" * 400, "doc")])
    req = IndexRequest(
        folder_path=".", chunk_size=512, chunk_overlap=50, include_code=True
    )
    with (
        patch(
            "brainpalace_server.services.indexing_service.load_provider_settings",
            return_value=_provider(
                "ollama", "nomic-embed-text"
            ),  # -> chars/4 heuristic
        ),
        _no_git(),
        _no_sessions(),
    ):
        est = await svc.estimate_tokens(req)

    assert est["files"] == 2
    assert est["code_files"] == 1
    assert est["doc_files"] == 1
    assert est["raw_tokens"] == 200  # ceil(400/4) * 2
    assert est["overlap_factor"] == round(1 + 50 / 512, 3)
    assert est["est_embedding_tokens"] == int(round(200 * (1 + 50 / 512)))
    assert est["tokenizer"].startswith("heuristic")
    assert est["approximate"] is True
    assert est["summaries_enabled"] is False


@pytest.mark.asyncio
async def test_estimate_uses_tiktoken_for_openai() -> None:
    svc = _service([_doc("hello world from brainpalace", "doc")])
    req = IndexRequest(folder_path=".", chunk_size=512, chunk_overlap=0)
    with (
        patch(
            "brainpalace_server.services.indexing_service.load_provider_settings",
            return_value=_provider("openai", "text-embedding-3-small"),
        ),
        _no_git(),
        _no_sessions(),
    ):
        est = await svc.estimate_tokens(req)

    assert est["tokenizer"].startswith("tiktoken:")
    assert est["raw_tokens"] > 0
    # No overlap -> embedded equals raw (doc-only, no git/sessions).
    assert est["est_embedding_tokens"] == est["raw_tokens"]


def test_effective_include_patterns_unions_presets() -> None:
    svc = IndexingService(storage_backend=MagicMock())
    req = IndexRequest(
        folder_path=".", include_patterns=["*.md"], include_types=["python"]
    )
    with patch(
        "brainpalace_server.services.file_type_presets.resolve_file_types",
        return_value=["*.py", "*.md"],
    ):
        patterns = svc._effective_include_patterns(req)
    assert "*.md" in patterns
    assert "*.py" in patterns
    assert patterns.count("*.md") == 1  # de-duped


# ---------------------------------------------------------------------------
# Phase 4 — git + session token accounting in estimate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_estimate_includes_git_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """estimate_tokens adds git_tokens when git_indexing.enabled=true."""
    repo = _make_git_repo(tmp_path)

    # Write a config.yaml that opts into git indexing.
    cfg_dir = repo / ".brainpalace"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "git_indexing:\n  enabled: true\n  depth: 0\n"
    )
    monkeypatch.setenv("BRAINPALACE_CONFIG", str(cfg_file))

    svc = _service([])  # no doc files — isolates git contribution
    req = IndexRequest(folder_path=str(repo))

    with (
        patch(
            "brainpalace_server.services.indexing_service.load_provider_settings",
            return_value=_provider("openai", "text-embedding-3-large"),
        ),
        _no_sessions(),
    ):
        est = await svc.estimate_tokens(req)

    assert "git_tokens" in est, "git_tokens key missing from estimate dict"
    assert est["git_tokens"] > 0, "expected positive git token count"
    assert "git_commits" in est
    assert est["git_commits"] == 2  # our 2-commit repo
    # total must be >= doc + git (sessions are 0 here)
    assert est["est_embedding_tokens"] >= est.get("doc_tokens", 0) + est["git_tokens"]


@pytest.mark.asyncio
async def test_estimate_git_disabled_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """estimate_tokens returns git_tokens=0 when git indexing is not enabled."""
    repo = _make_git_repo(tmp_path)

    cfg_dir = repo / ".brainpalace"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    # No git_indexing block → disabled by default.
    cfg_file.write_text("embedding:\n  provider: ollama\n  model: nomic-embed-text\n")
    monkeypatch.setenv("BRAINPALACE_CONFIG", str(cfg_file))

    svc = _service([])
    req = IndexRequest(folder_path=str(repo))

    with patch(
        "brainpalace_server.services.indexing_service.load_provider_settings",
        return_value=_provider("ollama", "nomic-embed-text"),
    ):
        est = await svc.estimate_tokens(req)

    assert est.get("git_tokens", 0) == 0
    assert est.get("git_commits", 0) == 0


@pytest.mark.asyncio
async def test_estimate_session_tokens_counted_when_index_enabled(
    tmp_path: Path,
) -> None:
    """estimate_tokens counts session tokens when indexing is on + archive exists."""
    from brainpalace_server.config.session_config import (
        SessionArchiveConfig,
        SessionIndexingConfig,
    )

    # Create a project folder with a session archive containing a real .jsonl file.
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Default archive.dir is ".brainpalace/session_archive" (relative to project root).
    archive_dir = project_dir / ".brainpalace" / "session_archive"
    archive_dir.mkdir(parents=True)

    # Write a non-trivial .jsonl file so _count() returns > 0.
    session_file = archive_dir / "2024-01-15-claude-code.jsonl"
    session_file.write_text(
        '{"role": "assistant", "content": "Here is the analysis of your codebase..."}\n'
        '{"role": "assistant", "content": "The main function handles routing."}\n'
        '{"role": "tool", "content": "Reading file: src/main.py"}\n'
    )

    # Build a SessionIndexingConfig with enabled=True and the default archive dir.
    sess_cfg = SessionIndexingConfig(
        enabled=True,
        archive=SessionArchiveConfig(dir=".brainpalace/session_archive"),
    )

    svc = _service([])  # no doc files — isolate session contribution
    req = IndexRequest(folder_path=str(project_dir))

    with (
        patch(
            "brainpalace_server.services.indexing_service.load_provider_settings",
            return_value=_provider("ollama", "nomic-embed-text"),
        ),
        _no_git(),
        patch(
            "brainpalace_server.config.session_config.load_session_indexing_config",
            return_value=sess_cfg,
        ),
    ):
        est = await svc.estimate_tokens(req)

    assert est["session_tokens"] > 0, "expected positive session token count"
    assert est["session_files"] >= 1, "expected at least one session file counted"
    assert (
        est["est_embedding_tokens"] >= est.get("doc_tokens", 0) + est["session_tokens"]
    )

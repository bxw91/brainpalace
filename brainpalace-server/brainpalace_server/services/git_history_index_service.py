"""Phase 130 — orchestrate git-history ingestion into the existing index.

Mirrors :class:`SessionIndexService`: discover commits since the persisted
last-indexed sha, chunk each via :class:`GitCommitChunker`, dedup against stored
chunk ids, embed only the new chunks, and upsert them into the shared
vector/BM25/metadata store tagged ``source_type="git_commit"``.

No LLM. OFF unless the project opts in (see :mod:`git_config`). The raw repo
stays the source-of-truth; only derived commit chunks are stored. The
last-indexed sha is persisted under the server state dir so incremental
re-indexing only walks ``<last>..HEAD``.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from brainpalace_server.config.git_config import GitIndexingConfig
from brainpalace_server.config.indexing_config import load_indexing_config
from brainpalace_server.indexing.git_chunker import GitCommitChunker
from brainpalace_server.indexing.git_loader import (
    git_toplevel,
    load_commits,
    resolve_commit_scope,
)
from brainpalace_server.services.indexing_service import (
    enforce_token_budget,
)
from brainpalace_server.storage_paths import state_file_path

logger = logging.getLogger(__name__)

_STATE_FILE = "git_index_state.json"


def load_git_last_sha(state_dir: str | Path | None, repo_key: str) -> str | None:
    """Read the persisted git-index last-sha for ``repo_key``, or ``None``.

    Shared by :class:`GitHistoryIndexService` (incremental indexing) and
    startup self-heal (bounding the wanted-set) so both read the exact same
    state file / key without diverging. ``None`` covers "no state dir",
    "never indexed", and "state file unreadable" alike — all mean the same
    thing to a caller: nothing recorded yet.
    """
    if not state_dir:
        return None
    path = state_file_path(Path(state_dir), _STATE_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    sha = data.get(repo_key)
    return sha if isinstance(sha, str) else None


class GitHistoryIndexService:
    """Ingest git commit history into the shared index."""

    def __init__(
        self,
        embedding_generator: Any,
        storage_backend: Any,
        state_dir: str | Path | None = None,
    ) -> None:
        self.embedding_generator = embedding_generator
        self.storage_backend = storage_backend
        self.state_dir = Path(state_dir) if state_dir else None

    # -- last-sha persistence ---------------------------------------------

    def _state_path(self) -> Path | None:
        return state_file_path(self.state_dir, _STATE_FILE) if self.state_dir else None

    def _load_state(self) -> dict[str, str]:
        path = self._state_path()
        if not path or not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_last_sha(self, repo_key: str, sha: str) -> None:
        path = self._state_path()
        if not path:
            return
        state = self._load_state()
        state[repo_key] = sha
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state))
        except OSError as exc:
            logger.warning("Could not persist git index state: %s", exc)

    # -- repo branch resolution -------------------------------------------

    @staticmethod
    def _current_branch(repo_path: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            return out or None
        except (subprocess.CalledProcessError, OSError):
            return None

    # -- public API --------------------------------------------------------

    async def index_repo(
        self, repo_path: str, config: GitIndexingConfig
    ) -> dict[str, Any]:
        """Index commits since the persisted last sha, if enabled. Idempotent."""
        summary: dict[str, Any] = {
            "enabled": config.enabled,
            "repo_path": repo_path,
            "commits_total": 0,
            "commits_new": 0,
            "skipped": 0,
            "last_sha": None,
        }
        if not config.enabled:
            return summary

        target = config.repo_path or repo_path
        repo_name = Path(target).name or "git"
        last_sha = load_git_last_sha(self.state_dir, target)

        scope_paths = resolve_commit_scope(target, config.path_filter)
        commits = load_commits(
            target, depth=config.depth, since_sha=last_sha, paths=scope_paths
        )
        summary["commits_total"] = len(commits)
        if not commits:
            return summary

        branch = self._current_branch(target)
        chunker = GitCommitChunker(max_files=config.max_files)

        new_chunks = []
        skipped = 0
        for rec in commits:
            for chunk in chunker.chunk(rec, repo_name=repo_name, branch=branch):
                existing = await self.storage_backend.get_by_id(chunk.chunk_id)
                if existing is None:
                    new_chunks.append(chunk)
                else:
                    skipped += 1

        if new_chunks:
            _budget = load_indexing_config().max_embed_tokens_per_job
            _tok = enforce_token_budget(new_chunks, limit=_budget, force=False)
            logger.info(
                "Git embedding budget check ok: ~%d tokens (limit %d)", _tok, _budget
            )
            from brainpalace_server.services.usage_metrics import (
                usage_scope,
            )  # noqa: PLC0415

            with usage_scope("git"):
                embeddings = await self.embedding_generator.embed_chunks(new_chunks)
            await self.storage_backend.upsert_documents(
                ids=[c.chunk_id for c in new_chunks],
                embeddings=embeddings,
                documents=[c.text for c in new_chunks],
                metadatas=[c.metadata.to_dict() for c in new_chunks],
            )

        # Plan C: deterministic commit graph (Commit modifies File /
        # authored_by Author). Best-effort — never fails the ingest; rides the
        # same incremental walk, so re-runs only touch new commits.
        summary["graph_triplets"] = 0
        try:
            from brainpalace_server.indexing.git_graph import (  # noqa: PLC0415
                write_commit_graph,
            )

            # ``git log --numstat`` paths are relative to the git toplevel,
            # not the (possibly sub-directory) indexed root — join onto the
            # toplevel so file ids match the canonical code File node ids.
            graph_root = str(git_toplevel(target) or target)
            summary["graph_triplets"] = write_commit_graph(
                commits, graph_root, max_cochange_files=config.max_files
            )
        except Exception as exc:  # noqa: BLE001 — graph must not break ingest
            logger.warning("Commit-graph write failed (ingest unaffected): %s", exc)

        # commits[0] is newest (git log default order) — persist as the new tip.
        newest_sha = commits[0].sha
        self._save_last_sha(target, newest_sha)

        summary["commits_new"] = len(new_chunks)
        summary["skipped"] = skipped
        summary["last_sha"] = newest_sha
        return summary

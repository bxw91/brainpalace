"""Plan C — deterministic commit→graph triplets (no LLM).

Pure functions only: the writer hook lives in
services/git_history_index_service.py. Cross-domain rule (Plan 4): the Commit
subject is domain 'git'; a linked File object stays domain 'code' via
object_domain — the write must never flip a code node into the git view.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from brainpalace_server.config import settings
from brainpalace_server.models.graph import GraphTriple
from brainpalace_server.storage.graph_store import get_graph_store_manager

if TYPE_CHECKING:
    from brainpalace_server.indexing.git_loader import CommitRecord

logger = logging.getLogger(__name__)

_DISPLAY_MAX = 80


def commit_id(sha: str) -> str:
    return f"git-commit:{sha}"


def author_id(email: str) -> str:
    return f"git-author:{email.strip().lower()}"


def commit_display(rec: CommitRecord) -> str:
    """Searchable display name: short sha + subject, capped for the browser."""
    text = f"{rec.sha[:8]} {rec.subject}".strip()
    return text[:_DISPLAY_MAX]


def _abs_posix(repo_root: str, rel_path: str) -> str:
    root = repo_root.replace("\\", "/").rstrip("/")
    return f"{root}/{rel_path.replace(chr(92), '/')}"


def commit_triplets(
    rec: CommitRecord,
    repo_root: str,
    existing_file_ids: set[str],
    max_cochange_files: int = 50,
) -> list[GraphTriple]:
    """Typed triplets for one commit.

    - ``modifies`` only onto File nodes that already exist (never-guess: no
      phantom code Files for vanished or never-indexed paths), and only when
      the commit touches <= ``max_cochange_files`` paths (bulk/merge commits
      poison the co-change signal).
    - ``authored_by`` always (unless the email is empty), keyed by email.
    - Provenance: ``source_file=commit:<sha>`` (fine-grained purge on history
      rewrite), ``source_chunk_id=git_commit:<sha>`` (the commit's own chunk,
      so --mode graph can surface the commit text).
    """
    cid = commit_id(rec.sha)
    cname = commit_display(rec)
    source_file = f"commit:{rec.sha}"
    chunk_id = f"git_commit:{rec.sha}"
    out: list[GraphTriple] = []

    if rec.author_email.strip():
        out.append(
            GraphTriple(
                subject=cname,
                predicate="authored_by",
                object=rec.author or rec.author_email,
                subject_type="Commit",
                object_type="Author",
                subject_id=cid,
                object_id=author_id(rec.author_email),
                subject_name=cname,
                object_name=rec.author or rec.author_email,
                source_chunk_id=chunk_id,
                source_file=source_file,
                domain="git",
            )
        )

    if len(rec.files_changed) > max_cochange_files:
        return out

    for rel in rec.files_changed:
        fid = _abs_posix(repo_root, rel)
        if fid not in existing_file_ids:
            continue
        fname = rel.rsplit("/", 1)[-1]
        out.append(
            GraphTriple(
                subject=cname,
                predicate="modifies",
                object=fname,
                subject_type="Commit",
                object_type="File",
                subject_id=cid,
                object_id=fid,
                subject_name=cname,
                object_name=fname,
                source_chunk_id=chunk_id,
                source_file=source_file,
                domain="git",
            )
        )
    return out


def write_commit_graph(
    commits: list[CommitRecord],
    repo_root: str,
    max_cochange_files: int = 50,
) -> int:
    """Write commit/author triplets for ``commits``. Fail-soft by design —
    callers wrap this; a graph problem must never fail the git ingest."""
    if not settings.ENABLE_GRAPH_INDEX or not commits:
        return 0
    mgr = get_graph_store_manager()
    mgr.initialize()

    root = repo_root.replace("\\", "/").rstrip("/")
    candidates = sorted(
        {
            _abs_posix(root, rel)
            for rec in commits
            if len(rec.files_changed) <= max_cochange_files
            for rel in rec.files_changed
        }
    )
    existing = mgr.existing_node_ids(candidates)

    written = 0
    # Iterate oldest-first (commits arrives newest-first from git log): author
    # display name is last-writer-wins on upsert_nodes, and constraint (d)
    # wants the LATEST-seen spelling to win, so the newest commit for a given
    # author must be written last within the batch.
    for rec in reversed(commits):
        # Purge-before-write: state-reset re-runs (last-SHA cleared) rewrite
        # this sha's edges from scratch; the manager's dedup-key eviction
        # rides on the same invalidate call. Append-only otherwise.
        mgr.invalidate_by_source_file(f"commit:{rec.sha}", domain="git")
        for tr in commit_triplets(
            rec, root, existing, max_cochange_files=max_cochange_files
        ):
            ok = mgr.add_triplet(
                subject=tr.subject,
                predicate=tr.predicate,
                obj=tr.object,
                subject_type=tr.subject_type,
                object_type=tr.object_type,
                source_chunk_id=tr.source_chunk_id,
                subject_id=tr.effective_subject_id,
                object_id=tr.effective_object_id,
                subject_name=tr.subject_name,
                object_name=tr.object_name,
                source_file=tr.source_file,
                domain="git",
                subject_domain="git",
                object_domain="code" if tr.predicate == "modifies" else "git",
            )
            if ok:
                written += 1
    # NO sweep_orphan_nodes(domain='git'): commits/authors are append-only and
    # temporal "as of" views must keep resolving swept-looking nodes.
    return written

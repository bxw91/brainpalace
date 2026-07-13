"""Phase 130 — walk a repo's ``git log`` into structured commit records.

Mirrors the 050 session *source* model rather than the file pipeline: a
non-file ingestion source that discovers history via ``subprocess`` + the ``git``
CLI (no new native dependency — libgit2 rejected to keep the no-Kuzu stance).

The parser pins a stable ``--pretty=format:`` with sentinel markers so the
multi-line commit body and the trailing ``--numstat`` block can be split
unambiguously. Parsing is deliberately tolerant: a non-repo / git failure yields
an empty list rather than raising, so the index service can no-op cleanly.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Sentinels — chosen to be vanishingly unlikely in real commit text.
_COMMIT = "\x1eABGIT_COMMIT\x1e"
_ENDMSG = "\x1eABGIT_ENDMSG\x1e"

#: Field order inside the header block (one field per line, body last).
_PRETTY = f"{_COMMIT}%n%H%n%an%n%ae%n%cI%n%s%n%b%n{_ENDMSG}"

# 0 = no cap (walk the entire history). See GitIndexingConfig.depth.
DEFAULT_DEPTH = 0


def git_toplevel(repo_path: str | Path) -> Path | None:
    """Return the git working-tree root for ``repo_path``, or None if not a repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return Path(out).resolve() if out else None
    except (subprocess.CalledProcessError, OSError):
        return None


def list_indexable_shas(
    repo_path: str | Path,
    *,
    depth: int = 0,
    paths: list[str] | None = None,
    rev: str | None = None,
) -> set[str] | None:
    """Shas the git indexer would walk: ``git log`` from HEAD, depth-capped,
    path-scoped — the same invocation shape as :func:`load_commits` minus the
    record payload. Returns ``None`` when they can't be determined (not a
    repo / git error / empty history), never raises.

    ``rev`` walks from that commit instead of the implicit ``HEAD`` — used by
    self-heal to bound the wanted-set by the git indexer's recorded progress
    rather than the live branch tip. An unreachable ``rev`` (e.g. GC'd after a
    history rewrite) makes ``git log`` fail, which correctly yields ``None``.
    """
    args = ["log", "--format=%H"]
    if depth and depth > 0:
        args.append(f"--max-count={depth}")
    if rev:
        args.append(rev)
    if paths:
        args.append("--")
        args.extend(paths)
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("list_indexable_shas failed for %s: %s", repo_path, exc)
        return None
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def resolve_commit_scope(
    project_root: str | Path, path_filter: list[str] | None
) -> list[str]:
    """Decide which ``git log -- <paths>`` to pass for a project.

    - An explicit ``path_filter`` always wins (returned unchanged).
    - Otherwise, when the project root is a *subdirectory* of a larger repo
      (monorepo), scope to the project subdir so only its commits are indexed.
    - When the project root IS the repo root, return ``[]`` (index all commits).
    """
    if path_filter:
        return list(path_filter)
    root = Path(project_root).resolve()
    top = git_toplevel(root)
    if top is not None and top != root:
        return [str(root)]
    return []


@dataclass
class CommitRecord:
    """One commit lifted from ``git log`` — message + diff stat summary."""

    sha: str
    author: str
    author_email: str
    committed_at: datetime
    subject: str
    body: str
    files_changed: list[str] = field(default_factory=list)
    lines_added: int = 0
    lines_deleted: int = 0


def _build_args(
    depth: int, since_sha: str | None, paths: list[str] | None = None
) -> list[str]:
    args = ["log"]
    # depth <= 0 means "no cap" — walk the entire history.
    if depth and depth > 0:
        args.append(f"--max-count={depth}")
    args += [
        "--numstat",
        "--no-color",
        f"--pretty=format:{_PRETTY}",
    ]
    if since_sha:
        args.append(f"{since_sha}..HEAD")
    if paths:
        args.append("--")
        args.extend(paths)
    return args


def _parse_numstat(line: str) -> tuple[str, int, int] | None:
    """Parse one ``added<TAB>deleted<TAB>path`` numstat row.

    Binary files report ``-`` for the counts; treat those as zero.
    """
    parts = line.split("\t")
    if len(parts) != 3:
        return None
    added_s, deleted_s, path = parts
    if not path:
        return None
    added = int(added_s) if added_s.isdigit() else 0
    deleted = int(deleted_s) if deleted_s.isdigit() else 0
    return path, added, deleted


def _parse(output: str) -> list[CommitRecord]:
    commits: list[CommitRecord] = []
    # Each record starts with the _COMMIT sentinel; the first split chunk is
    # empty (leading sentinel), so skip falsy chunks.
    for chunk in output.split(_COMMIT):
        if not chunk.strip():
            continue
        header, _, tail = chunk.partition(_ENDMSG)
        lines = header.split("\n")
        # lines[0] is empty (the %n right after the sentinel).
        fields = lines[1:]
        if len(fields) < 5:
            continue
        sha, author, email, date_iso, subject = fields[:5]
        body = "\n".join(fields[5:]).strip()
        try:
            committed_at = datetime.fromisoformat(date_iso.strip())
        except ValueError:
            continue

        files: list[str] = []
        added_total = 0
        deleted_total = 0
        for raw in tail.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            parsed = _parse_numstat(raw)
            if parsed is None:
                continue
            path, added, deleted = parsed
            files.append(path)
            added_total += added
            deleted_total += deleted

        commits.append(
            CommitRecord(
                sha=sha.strip(),
                author=author.strip(),
                author_email=email.strip(),
                committed_at=committed_at,
                subject=subject.strip(),
                body=body,
                files_changed=files,
                lines_added=added_total,
                lines_deleted=deleted_total,
            )
        )
    return commits


def load_commits(
    repo_path: str | Path,
    depth: int = DEFAULT_DEPTH,
    since_sha: str | None = None,
    paths: list[str] | None = None,
) -> list[CommitRecord]:
    """Return commit records newest-first, or ``[]`` for a non-repo / failure."""
    repo = Path(repo_path)
    if not repo.exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *_build_args(depth, since_sha, paths)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.debug("git log failed for %s: %s", repo, exc)
        return []
    return _parse(proc.stdout)

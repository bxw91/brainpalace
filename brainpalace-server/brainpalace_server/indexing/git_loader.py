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

DEFAULT_DEPTH = 1000


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


def _build_args(depth: int, since_sha: str | None) -> list[str]:
    args = [
        "log",
        f"--max-count={depth}",
        "--numstat",
        "--no-color",
        f"--pretty=format:{_PRETTY}",
    ]
    if since_sha:
        args.append(f"{since_sha}..HEAD")
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
) -> list[CommitRecord]:
    """Return commit records newest-first, or ``[]`` for a non-repo / failure."""
    repo = Path(repo_path)
    if not repo.exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *_build_args(depth, since_sha)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.debug("git log failed for %s: %s", repo, exc)
        return []
    return _parse(proc.stdout)

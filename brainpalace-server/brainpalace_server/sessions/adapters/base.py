"""Protocol every session tool adapter implements.

An adapter owns the three tool-shaped concerns — where transcripts live, which
of them belong to this project, and how one file parses into the shared
``(SessionMeta, list[Turn])`` pair. Everything downstream (archive, chunker,
distiller, extraction subagents) consumes only that pair and stays
format-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from brainpalace_server.indexing.session_loader import SessionMeta, Turn


@runtime_checkable
class SessionToolAdapter(Protocol):
    """One AI coding tool's on-disk transcript store."""

    slug: str

    def source_dirs(self, project_root: str, home: Path) -> list[Path]:
        """Root directories this tool may keep transcripts in."""
        ...

    def discover(self, src: Path, project_root: str) -> list[Path]:
        """Transcript files under ``src``. Does NOT filter by project."""
        ...

    def owns(self, path: Path, project_root: str) -> bool:
        """True when ``path`` belongs to ``project_root``.

        MUST be correct for tools with a global, cross-project store: a False
        negative loses a session, a False positive leaks another project's raw
        transcript into this project's archive.
        """
        ...

    def parse(
        self, path: Path, *, text_trunc: int = 1500
    ) -> tuple[SessionMeta, list[Turn]]:
        """Parse one transcript into the shared metadata + turns pair."""
        ...

    def title(self, path: Path, max_chars: int = 120) -> str | None:
        """First human prompt line, for a session title. None when absent."""
        ...

    def is_subagent(self, path: Path) -> bool:
        """True when this transcript is a sub-agent of another session."""
        ...

    def parent_session_id(self, path: Path) -> str | None:
        """Parent session id for a sub-agent transcript, else None."""
        ...


@dataclass(frozen=True)
class SessionSource:
    """One (adapter, directory) pair to sweep."""

    adapter: SessionToolAdapter
    directory: Path

    @property
    def slug(self) -> str:
        return self.adapter.slug

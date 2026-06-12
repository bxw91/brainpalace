"""Manifest tracker for per-folder incremental indexing.

This module provides the ManifestTracker service which maintains per-folder
JSON manifests recording file checksums, mtimes, and chunk IDs. It enables
incremental indexing by detecting which files have changed since the last
index run.

Manifest path: <manifests_dir>/<sha256(folder_path)>.json
Atomic writes via temp + Path.replace() for crash safety.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FileRecord:
    """Per-file record stored in a folder manifest.

    Attributes:
        checksum: SHA-256 hex digest of the file's content
        mtime: File modification time as float seconds (os.stat().st_mtime)
        chunk_ids: List of chunk IDs produced from this file during indexing
        last_embedded_at: Epoch seconds of the last time this file was embedded
            (Phase L). 0.0 = never recorded (legacy manifest / first index) —
            the re-embed cooldown treats that as "embed once".
        size_bytes: File size in bytes at last embed (Phase L). 0 = unknown
            (legacy manifest).
        pending_reindex: Self-heal found some of this file's chunks
            unrecoverable. The record (and its surviving chunk ids) is kept —
            so recovery keeps wanting the missing chunks and deep-clean spares
            the survivors — and the eviction diff forces a reindex regardless
            of mtime/checksum. Cleared by the fresh record the successful
            reindex writes (drop-after-verify).
    """

    checksum: str
    mtime: float
    chunk_ids: list[str]
    last_embedded_at: float = 0.0
    size_bytes: int = 0
    pending_reindex: bool = False


@dataclass
class FolderManifest:
    """Full manifest for one indexed folder.

    Attributes:
        folder_path: Absolute path to the indexed folder
        files: Mapping of absolute file path strings to FileRecord objects
    """

    folder_path: str
    files: dict[str, FileRecord] = field(default_factory=dict)


@dataclass
class EvictionSummary:
    """Result of a manifest diff and chunk eviction pass.

    Attributes:
        files_added: New files not present in prior manifest
        files_changed: Files whose content checksum changed
        files_deleted: Files present in prior manifest but not on disk
        files_unchanged: Files with matching mtime/checksum (skipped)
        chunks_evicted: Total chunk IDs deleted from storage backend
        chunks_to_create: Number of files requiring (re-)indexing
        files_deferred: Large changed files skipped this run by the re-embed
            cooldown (Phase L). Their existing chunks are kept and their prior
            FileRecord is preserved so they re-check the cooldown next run.
        deferred_evict_ids: Old chunk ids of CHANGED files whose eviction was
            held back for the atomic add-then-swap reindex — the caller deletes
            them only AFTER the new chunks are safely upserted, so a crash
            mid-reindex leaves the old chunks intact instead of losing data.
            Distinct from ``files_deferred`` (a re-embed-cooldown concept).
        files_out_of_scope: Prior-manifest files the current run did NOT load
            but that still exist on disk — out of the run's scope (e.g. an
            include_code=False run over a folder previously indexed with code),
            NOT deletions. Their chunks survive and their records carry over
            (they are also listed in ``files_unchanged`` for that purpose).
    """

    files_added: list[str]
    files_changed: list[str]
    files_deleted: list[str]
    files_unchanged: list[str]
    chunks_evicted: int
    chunks_to_create: int
    files_deferred: list[str] = field(default_factory=list)
    deferred_evict_ids: list[str] = field(default_factory=list)
    files_out_of_scope: list[str] = field(default_factory=list)


class ManifestTracker:
    """Tracks per-folder file manifests for incremental indexing.

    Stores one JSON file per indexed folder at:
        <manifests_dir>/<sha256(folder_path)>.json

    Uses atomic write (temp + Path.replace()) for crash safety and
    a single asyncio.Lock for all manifest operations.

    Mirrors the FolderManager async/lock/atomic-write pattern established
    in Phase 12.
    """

    def __init__(self, manifests_dir: Path) -> None:
        """Initialize ManifestTracker.

        Args:
            manifests_dir: Directory for manifest file storage
        """
        self.manifests_dir = manifests_dir
        self._lock = asyncio.Lock()

    def _manifest_path(self, folder_path: str) -> Path:
        """Compute the manifest file path for a given folder.

        Uses SHA-256 of the folder path string as the filename to avoid
        path-separator issues and keep the manifests directory flat.

        Args:
            folder_path: Absolute path to the indexed folder

        Returns:
            Path to the manifest JSON file
        """
        key = hashlib.sha256(folder_path.encode()).hexdigest()
        return self.manifests_dir / f"{key}.json"

    async def load(self, folder_path: str) -> FolderManifest | None:
        """Load manifest for folder, returns None if not present.

        Args:
            folder_path: Absolute path to the indexed folder

        Returns:
            FolderManifest if manifest file exists, None otherwise

        Raises:
            OSError: If manifest file exists but cannot be read
            json.JSONDecodeError: If manifest file contains invalid JSON
        """
        path = self._manifest_path(folder_path)
        if not path.exists():
            return None
        return await asyncio.to_thread(self._read_manifest, path, folder_path)

    async def save(self, manifest: FolderManifest) -> None:
        """Atomically persist manifest to disk.

        Uses temp file + Path.replace() for crash safety. Under lock
        to prevent concurrent writes to the same manifest.

        Args:
            manifest: FolderManifest to persist

        Raises:
            OSError: If manifest cannot be written
        """
        async with self._lock:
            await asyncio.to_thread(self._write_manifest, manifest)

    async def delete(self, folder_path: str) -> None:
        """Remove manifest file.

        Used on folder removal or force reindex. No-op if manifest
        does not exist.

        Args:
            folder_path: Absolute path to the indexed folder

        Raises:
            OSError: If manifest file exists but cannot be deleted
        """
        path = self._manifest_path(folder_path)
        async with self._lock:
            if path.exists():
                await asyncio.to_thread(path.unlink)
                logger.debug(f"Deleted manifest for {folder_path}")

    async def delete_all(self) -> int:
        """Remove every manifest file in the manifests directory.

        Used on a full index reset so a subsequent re-index does not read a
        stale manifest and conclude every file is unchanged (which would leave
        the stores empty while the manifest still tracks files). No-op if the
        directory does not exist.

        Returns:
            Number of manifest files deleted.

        Raises:
            OSError: If a manifest file exists but cannot be deleted.
        """
        async with self._lock:
            return await asyncio.to_thread(self._delete_all_sync)

    def _delete_all_sync(self) -> int:
        """Delete all ``*.json`` manifest files (synchronous, under lock)."""
        if not self.manifests_dir.exists():
            return 0
        deleted = 0
        for manifest_file in self.manifests_dir.glob("*.json"):
            manifest_file.unlink()
            deleted += 1
        if deleted:
            logger.info(f"Deleted {deleted} manifest file(s) on reset")
        return deleted

    def _read_manifest(self, path: Path, folder_path: str) -> FolderManifest:
        """Deserialize manifest from JSON file (synchronous).

        Args:
            path: Path to the manifest JSON file
            folder_path: Folder path for the manifest

        Returns:
            Deserialized FolderManifest

        Raises:
            OSError: If file cannot be read
            json.JSONDecodeError: If file contains invalid JSON
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        files = {
            fp: FileRecord(
                checksum=rec["checksum"],
                mtime=rec["mtime"],
                chunk_ids=rec["chunk_ids"],
                # Phase L fields — absent in legacy manifests, default to 0.
                last_embedded_at=rec.get("last_embedded_at", 0.0),
                size_bytes=rec.get("size_bytes", 0),
                pending_reindex=rec.get("pending_reindex", False),
            )
            for fp, rec in data.get("files", {}).items()
        }
        return FolderManifest(folder_path=folder_path, files=files)

    def _write_manifest(self, manifest: FolderManifest) -> None:
        """Serialize and atomically write manifest to JSON file (synchronous).

        Creates manifests directory if it does not exist. Uses a temporary
        file and atomic rename (Path.replace()) for crash safety.

        Must be called under self._lock.

        Args:
            manifest: FolderManifest to serialize

        Raises:
            OSError: If manifest cannot be written
        """
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        path = self._manifest_path(manifest.folder_path)
        temp_path = path.with_suffix(".json.tmp")
        data = {
            "folder_path": manifest.folder_path,
            "files": {
                fp: {
                    "checksum": rec.checksum,
                    "mtime": rec.mtime,
                    "chunk_ids": rec.chunk_ids,
                    "last_embedded_at": rec.last_embedded_at,
                    "size_bytes": rec.size_bytes,
                    "pending_reindex": rec.pending_reindex,
                }
                for fp, rec in manifest.files.items()
            },
        }
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        temp_path.replace(path)  # POSIX atomic rename


def compute_file_checksum(file_path: str) -> str:
    """Compute SHA-256 hex digest of file contents.

    Reads the file in 64 KB chunks to handle large files without
    loading the entire file into memory.

    Args:
        file_path: Absolute path to the file

    Returns:
        SHA-256 hex digest string (64 hex characters)

    Raises:
        OSError: If file cannot be read
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

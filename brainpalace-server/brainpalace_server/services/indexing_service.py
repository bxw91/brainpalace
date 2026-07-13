"""Indexing service that orchestrates the document indexing pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brainpalace_server.services.content_injector import ContentInjector
    from brainpalace_server.services.folder_manager import FolderManager
    from brainpalace_server.services.manifest_tracker import ManifestTracker

from llama_index.core.schema import TextNode

from brainpalace_server.config import settings
from brainpalace_server.config.bm25_config import load_bm25_config
from brainpalace_server.config.provider_config import load_provider_settings
from brainpalace_server.indexing import (
    BM25IndexManager,
    ContextAwareChunker,
    DocumentLoader,
    EmbeddingGenerator,
    get_bm25_manager,
)
from brainpalace_server.indexing.chunking import CodeChunk, CodeChunker, TextChunk
from brainpalace_server.indexing.graph_index import (
    GraphIndexManager,
    get_graph_index_manager,
)
from brainpalace_server.models import IndexingState, IndexingStatusEnum, IndexRequest
from brainpalace_server.storage import (
    StorageBackendProtocol,
    VectorStoreManager,
    get_storage_backend,
    get_vector_store,
)

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when an index job would embed more tokens than the configured budget."""

    def __init__(self, message: str, *, estimated_tokens: int, limit: int) -> None:
        super().__init__(message)
        self.estimated_tokens = estimated_tokens
        self.limit = limit


def estimate_chunk_tokens(chunks: list[Any]) -> int:
    """Cheap ceil(len/4) token sum over chunk .text — provider-agnostic, no API."""
    return sum(-(-len(getattr(c, "text", "") or "") // 4) for c in chunks)


def enforce_token_budget(chunks: list[Any], *, limit: int, force: bool) -> int:
    """Raise BudgetExceededError when the to-embed tokens exceed ``limit``.

    ``limit <= 0`` disables the guard. ``force`` bypasses it (explicit opt-in).
    Returns the estimated token total for logging.
    """
    total = estimate_chunk_tokens(chunks)
    if limit > 0 and not force and total > limit:
        raise BudgetExceededError(
            f"Index would embed ~{total:,} tokens, over the budget of {limit:,}. "
            f"Raise indexing.max_embed_tokens_per_job or re-run with "
            f"force_budget=true.",
            estimated_tokens=total,
            limit=limit,
        )
    return total


def effective_token_budget(
    *, floor: int, ratio: float, total_chunks: int, chunk_size: int
) -> int:
    """Effective per-job embedding-token cap: max(floor, ratio × index size).

    ``floor <= 0`` keeps the guard fully disabled (returns floor unchanged);
    ``ratio <= 0`` restores the pure fixed cap. Index size is the loose
    ``total_chunks * chunk_size`` estimate — erring high, which only ever
    RAISES the cap (fewer false trips; approve-flow covers the rest).
    """
    if floor <= 0 or ratio <= 0:
        return floor
    return max(floor, int(ratio * total_chunks * chunk_size))


# Type alias for progress callback.
# Args: (percent_current, percent_total, message, files_processed?, files_total?)
# — the two leading ints are the phase-weighted percent pair (total is 100); the
# trailing two optional ints carry real document counts for display.
ProgressCallback = Callable[..., Awaitable[None]]


def _folder_chunk_ids(manifest: Any) -> list[str]:
    """Authoritative folder chunk-id set: sorted union over the *current*
    per-file manifest records.

    The per-file manifest carries unchanged files (so their chunks are retained)
    and excludes deleted/changed-old chunks (evicted, never re-recorded). Deriving
    the folder count from it makes the count self-heal — it shrinks when files are
    removed instead of growing monotonically the way a blind union of old+new ids
    did (which diverged far above the real store).
    """
    ids: set[str] = set()
    for rec in manifest.files.values():
        ids.update(rec.chunk_ids)
    return sorted(ids)


def _is_initial_index(manifest_tracker: Any, prior_manifest: Any) -> bool:
    """True when this run is a folder's FIRST index — exempt from the budget guard.

    First index ⇔ manifest tracking is active AND the folder has no prior
    authoritative chunks (no manifest on disk, or an empty one). The cap exists to
    catch surprise re-embed cost on watch/incremental/auto re-indexes, never the
    deliberate initial index the user explicitly asked for.

    When manifest tracking is OFF the tracker is None and ``prior_manifest`` is
    unconditionally None, which must NOT be read as "first index" — that would
    silently disable the guard on every run. Hence the ``manifest_tracker is not
    None`` gate is load-bearing, not defensive.
    """
    if manifest_tracker is None:
        return False
    return prior_manifest is None or not _folder_chunk_ids(prior_manifest)


def _classify_documents(paths: set[str]) -> dict[str, int]:
    """Split a set of indexed file paths into code vs doc counts by extension.

    Code := extension in DocumentLoader.CODE_EXTENSIONS; everything else
    (e.g. .md, .html) is a doc — matching the loader's own default.
    """
    code_exts = DocumentLoader.CODE_EXTENSIONS
    code = sum(1 for p in paths if Path(p).suffix.lower() in code_exts)
    total = len(paths)
    return {"code": code, "doc": total - code, "total": total}


def _folder_bucket(file_path: str, root: str) -> str:
    """First path component of ``file_path`` relative to ``root``; loose files
    directly in ``root`` bucket to ``"(root files)"``."""
    try:
        rel = os.path.relpath(file_path, root)
    except ValueError:  # different drive / unrelated path
        return "(root files)"
    parts = rel.split(os.sep)
    if len(parts) <= 1 or parts[0] in ("", ".", ".."):
        return "(root files)"
    return parts[0]


def _resolve_watch_settings(
    *,
    has_existing: bool,
    existing_watch_mode: str | None,
    existing_debounce: int | None,
    request_watch_mode: str | None,
    request_debounce: int | None,
) -> tuple[str, int | None]:
    """Decide the (watch_mode, debounce) to persist for a folder index.

    Rules:
      - An explicit ``request.watch_mode`` (not None) always wins — it can
        upgrade off->auto or downgrade auto->off, on a new folder or a
        re-index. This is what lets a fresh first index persist 'auto'
        immediately, before the rebuildable BM25/graph tail, so an interrupt
        mid-tail can't strand the folder as unwatched.
      - No flag on this run + an existing folder -> preserve its settings
        (a plain reindex must not silently reset auto back to off).
      - No flag + new folder -> default 'off'.
    """
    if request_watch_mode is not None:
        return request_watch_mode, request_debounce
    if has_existing:
        return existing_watch_mode or "off", existing_debounce
    return "off", None


class IndexingService:
    """
    Orchestrates the document indexing pipeline.

    Coordinates document loading, chunking, embedding generation,
    and vector store storage with progress tracking.
    """

    def __init__(
        self,
        vector_store: VectorStoreManager | None = None,
        document_loader: DocumentLoader | None = None,
        chunker: ContextAwareChunker | None = None,
        embedding_generator: EmbeddingGenerator | None = None,
        bm25_manager: BM25IndexManager | None = None,
        graph_index_manager: GraphIndexManager | None = None,
        storage_backend: StorageBackendProtocol | None = None,
        folder_manager: FolderManager | None = None,
        manifest_tracker: ManifestTracker | None = None,
    ):
        """
        Initialize the indexing service.

        Args:
            vector_store: [DEPRECATED] Vector store manager
                (for backward compat).
            document_loader: Document loader instance.
            chunker: Text chunker instance.
            embedding_generator: Embedding generator instance.
            bm25_manager: [DEPRECATED] BM25 index manager
                (for backward compat).
            graph_index_manager: Graph index manager instance (Feature 113).
            storage_backend: Storage backend implementing protocol (preferred).
            folder_manager: Optional folder manager for indexed folder tracking.
            manifest_tracker: Optional manifest tracker for incremental indexing
                (Phase 14).
        """
        # Resolve storage_backend with backward compatibility
        if storage_backend is not None:
            self.storage_backend = storage_backend
        elif vector_store is not None or bm25_manager is not None:
            # Legacy path: wrap provided stores in ChromaBackend
            from brainpalace_server.storage.chroma.backend import ChromaBackend

            self.storage_backend = ChromaBackend(
                vector_store=vector_store,
                bm25_manager=bm25_manager,
            )
        else:
            # New path: use factory
            self.storage_backend = get_storage_backend()

        # Maintain backward-compatible aliases
        if hasattr(self.storage_backend, "vector_store"):
            self.vector_store = self.storage_backend.vector_store
        else:
            self.vector_store = vector_store or get_vector_store()

        if hasattr(self.storage_backend, "bm25_manager"):
            self.bm25_manager = self.storage_backend.bm25_manager
        else:
            self.bm25_manager = bm25_manager or get_bm25_manager()

        self.document_loader = document_loader or DocumentLoader()
        self.chunker = chunker or ContextAwareChunker()
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.graph_index_manager = graph_index_manager or get_graph_index_manager()
        self.folder_manager = folder_manager
        self.manifest_tracker = manifest_tracker

        # Internal state
        self._state = IndexingState(
            current_job_id="",
            folder_path="",
            started_at=None,
            completed_at=None,
            error=None,
        )
        self._lock = asyncio.Lock()
        self._indexed_folders: set[str] = set()
        self._total_doc_chunks = 0
        self._total_code_chunks = 0
        self._supported_languages: set[str] = set()

    @property
    def state(self) -> IndexingState:
        """Get the current indexing state."""
        return self._state

    @property
    def is_indexing(self) -> bool:
        """Check if indexing is currently in progress."""
        return self._state.is_indexing

    @property
    def is_ready(self) -> bool:
        """Check if the system is ready for queries."""
        return (
            self.storage_backend.is_initialized
            and not self.is_indexing
            and self._state.status != IndexingStatusEnum.FAILED
        )

    async def start_indexing(
        self,
        request: IndexRequest,
        progress_callback: ProgressCallback | None = None,
        force: bool = False,
    ) -> str:
        """
        Start a new indexing job.

        Args:
            request: IndexRequest with folder path and configuration.
            progress_callback: Optional callback for progress updates.
            force: If True, bypass embedding compatibility validation.

        Returns:
            Job ID for tracking the indexing operation.

        Raises:
            RuntimeError: If indexing is already in progress.
        """
        async with self._lock:
            if self._state.is_indexing:
                raise RuntimeError("Indexing already in progress")

            # Validate embedding compatibility unless force=True
            if not force:
                await self._validate_embedding_compatibility()

            # Generate job ID and initialize state
            job_id = f"job_{uuid.uuid4().hex[:12]}"
            self._state = IndexingState(
                current_job_id=job_id,
                status=IndexingStatusEnum.INDEXING,
                is_indexing=True,
                folder_path=request.folder_path,
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                error=None,
            )

        logger.info(f"Starting indexing job {job_id} for {request.folder_path}")

        # Run indexing in background
        asyncio.create_task(
            self._run_indexing_pipeline(request, job_id, progress_callback)
        )

        return job_id

    async def _validate_embedding_compatibility(self) -> None:
        """Validate current embedding config matches existing index.

        Raises:
            ProviderMismatchError: If provider/model/dimensions don't match
        """
        # Get stored metadata
        stored_metadata = await self.storage_backend.get_embedding_metadata()

        if stored_metadata is None:
            # No existing index, no validation needed
            return

        # Get current config
        provider_settings = load_provider_settings()
        _provider = provider_settings.embedding.provider
        # (str, Enum) → str() gives "EmbeddingProviderType.OPENAI"; stored metadata
        # holds the value ("openai"). Use .value so re-index doesn't false-mismatch.
        current_provider = getattr(_provider, "value", str(_provider))
        current_model = provider_settings.embedding.model
        current_dimensions = self.embedding_generator.get_embedding_dimensions()

        # Validate
        self.storage_backend.validate_embedding_compatibility(
            provider=current_provider,
            model=current_model,
            dimensions=current_dimensions,
            stored_metadata=stored_metadata,
        )

    def _effective_include_patterns(self, request: IndexRequest) -> list[str]:
        """Resolve include_types presets into the effective include-pattern set.

        Single source of truth shared by the real pipeline and the dry-run
        token estimate, so the estimate's file selection can never drift from
        what indexing actually loads.
        """
        effective = list(request.include_patterns or [])
        if request.include_types:
            from brainpalace_server.services.file_type_presets import (
                resolve_file_types,
            )

            for pattern in resolve_file_types(request.include_types):
                if pattern not in effective:
                    effective.append(pattern)
        return effective

    async def estimate_tokens(self, request: IndexRequest) -> dict[str, Any]:
        """Approximate the embedding-token cost of indexing ``request`` — no
        embedding, no enqueue, no provider calls.

        Loads exactly the files the real pipeline would (same
        ``document_loader.load_files`` call, honouring .gitignore, default
        excludes, nested-project exclusion, include/exclude patterns and file
        types), then counts tokens with the embedding provider's own tokenizer
        (tiktoken for OpenAI; a chars/4 heuristic otherwise) and inflates by the
        chunk-overlap ratio. The result is intentionally approximate.
        """
        abs_folder_path = os.path.abspath(request.folder_path)
        effective_include_patterns = self._effective_include_patterns(request)
        documents = await self.document_loader.load_files(
            abs_folder_path,
            recursive=request.recursive,
            include_code=request.include_code,
            include_patterns=effective_include_patterns or None,
        )

        provider_settings = load_provider_settings()
        _provider = provider_settings.embedding.provider
        provider = getattr(_provider, "value", str(_provider)).lower()
        model = str(provider_settings.embedding.model)

        # Pick the most accurate tokenizer available for the provider.
        encoder = None
        tokenizer = "heuristic(chars/4)"
        if provider == "openai":
            try:
                import tiktoken

                try:
                    encoder = tiktoken.encoding_for_model(model)
                except KeyError:
                    encoder = tiktoken.get_encoding("cl100k_base")
                tokenizer = f"tiktoken:{encoder.name}"
            except Exception:  # pragma: no cover - tiktoken always present
                encoder = None

        def _count(text: str) -> int:
            if encoder is not None:
                return len(encoder.encode(text, disallowed_special=()))
            return -(-len(text) // 4)  # ceil(len/4)

        from collections import defaultdict

        raw_tokens = 0
        code_files = 0
        doc_files = 0
        total_bytes = 0
        folder_files: dict[str, int] = defaultdict(int)
        folder_code_raw: dict[str, int] = defaultdict(int)
        folder_doc_raw: dict[str, int] = defaultdict(int)
        for d in documents:
            t = _count(d.text)
            raw_tokens += t
            total_bytes += d.file_size
            bucket = _folder_bucket(d.file_path, abs_folder_path)
            folder_files[bucket] += 1
            if d.metadata.get("source_type") == "code":
                code_files += 1
                folder_code_raw[bucket] += t
            else:
                doc_files += 1
                folder_doc_raw[bucket] += t

        # Chunk overlap re-embeds the overlap region of each chunk, so embedded
        # tokens exceed raw tokens by roughly overlap/chunk_size.
        chunk_size = request.chunk_size or 512
        overlap_factor = 1.0 + (request.chunk_overlap or 0) / max(chunk_size, 1)
        doc_tokens = int(round(raw_tokens * overlap_factor))

        by_folder = [
            {
                "name": name,
                "files": folder_files[name],
                "code_tokens": int(round(folder_code_raw[name] * overlap_factor)),
                "doc_tokens": int(round(folder_doc_raw[name] * overlap_factor)),
            }
            for name in folder_files
        ]

        # --- git history (same scope the real index uses; Phase 1) ---
        git_tokens = 0
        git_commits = 0
        from brainpalace_server.config.git_config import (
            load_git_indexing_config,
        )  # noqa: PLC0415

        git_cfg = load_git_indexing_config()
        if git_cfg.enabled:
            from brainpalace_server.indexing.git_chunker import (
                GitCommitChunker,
            )  # noqa: PLC0415
            from brainpalace_server.indexing.git_loader import (  # noqa: PLC0415
                load_commits,
                resolve_commit_scope,
            )

            repo_path = git_cfg.repo_path or abs_folder_path
            _max_files = git_cfg.max_files
            _depth = git_cfg.depth
            _repo_name = os.path.basename(abs_folder_path) or "git"

            def _count_git_commits() -> tuple[int, int]:
                scope = resolve_commit_scope(repo_path, git_cfg.path_filter or None)
                commits = load_commits(repo_path, depth=_depth, paths=scope or None)
                chunker = GitCommitChunker(max_files=_max_files)
                tokens = 0
                for rec in commits:
                    for ch in chunker.chunk(rec, repo_name=_repo_name, branch=None):
                        tokens += _count(ch.text)
                return tokens, len(commits)

            git_tokens, git_commits = await asyncio.to_thread(_count_git_commits)

        # --- session transcripts (only when session indexing is enabled) ---
        session_tokens = 0
        session_files = 0
        from brainpalace_server.config.session_config import (  # noqa: PLC0415
            load_session_indexing_config,
            resolve_session_capabilities,
        )

        sess_cfg = load_session_indexing_config()
        caps = resolve_session_capabilities(sess_cfg)
        if caps.index_enabled:
            archive_dir = sess_cfg.archive.dir
            if os.path.isabs(archive_dir):
                archive_root = Path(archive_dir)
            else:
                archive_root = Path(abs_folder_path) / archive_dir
            if archive_root.exists():
                # Session transcripts use their own window/stride chunking, so
                # the doc overlap factor is intentionally NOT applied here; it's
                # an approximation of the raw transcript token cost only.
                def _count_session_files(root: Path) -> tuple[int, int]:
                    tokens, files = 0, 0
                    for f in root.rglob("*.jsonl"):
                        try:
                            tokens += _count(f.read_text(errors="replace"))
                            files += 1
                        except OSError:
                            continue
                    return tokens, files

                session_tokens, session_files = await asyncio.to_thread(
                    _count_session_files, archive_root
                )

        total_tokens = doc_tokens + git_tokens + session_tokens

        return {
            "files": len(documents),
            "code_files": code_files,
            "doc_files": doc_files,
            "total_bytes": total_bytes,
            "raw_tokens": raw_tokens,
            "doc_tokens": doc_tokens,
            "git_tokens": git_tokens,
            "git_commits": git_commits,
            "session_tokens": session_tokens,
            "session_files": session_files,
            "by_folder": by_folder,
            "est_embedding_tokens": total_tokens,
            "overlap_factor": round(overlap_factor, 3),
            "tokenizer": tokenizer,
            "embedding_provider": provider,
            "embedding_model": model,
            "approximate": True,
        }

    async def _run_indexing_pipeline(
        self,
        request: IndexRequest,
        job_id: str,
        progress_callback: ProgressCallback | None = None,
        content_injector: ContentInjector | None = None,
    ) -> dict[str, Any] | None:
        """
        Execute the full indexing pipeline.

        Args:
            request: Indexing request configuration.
            job_id: Job identifier for tracking.
            progress_callback: Optional progress callback.
            content_injector: Optional content injector for metadata enrichment.

        Returns:
            Eviction summary dict if manifest tracking is active, None otherwise.
        """
        eviction_summary_result: dict[str, Any] | None = None
        try:
            # Ensure storage backend is initialized
            await self.storage_backend.initialize()

            # Get current embedding config for metadata storage
            provider_settings = load_provider_settings()
            _provider = provider_settings.embedding.provider
            current_provider = getattr(_provider, "value", str(_provider))
            current_model = provider_settings.embedding.model
            current_dimensions = self.embedding_generator.get_embedding_dimensions()

            # Validate embedding compatibility unless force=True
            if not request.force:
                stored_metadata = await self.storage_backend.get_embedding_metadata()
                if stored_metadata is not None:
                    self.storage_backend.validate_embedding_compatibility(
                        provider=current_provider,
                        model=current_model,
                        dimensions=current_dimensions,
                        stored_metadata=stored_metadata,
                    )

            # Step 1: Load documents
            if progress_callback:
                await progress_callback(0, 100, "Loading documents...")

            # Normalize folder path to absolute path to avoid duplicates
            abs_folder_path = os.path.abspath(request.folder_path)
            logger.info(
                f"Normalizing indexing path: {request.folder_path} -> {abs_folder_path}"
            )

            # Resolve file type presets to glob patterns (FTYPE-03, FTYPE-06)
            effective_include_patterns = self._effective_include_patterns(request)

            documents = await self.document_loader.load_files(
                abs_folder_path,
                recursive=request.recursive,
                include_code=request.include_code,
                include_patterns=effective_include_patterns or None,
            )

            self._state.total_documents = len(documents)
            logger.info(f"Loaded {len(documents)} documents")

            # Manifest tracking for incremental indexing (Phase 14)
            eviction_summary: Any = None
            prior_manifest: Any = None

            if self.manifest_tracker is not None:
                from pathlib import Path as _Path

                from brainpalace_server.services.chunk_eviction_service import (
                    ChunkEvictionService,
                )
                from brainpalace_server.services.manifest_tracker import (
                    FolderManifest,
                )

                eviction_service = ChunkEvictionService(
                    manifest_tracker=self.manifest_tracker,
                    storage_backend=self.storage_backend,
                )
                current_file_paths = [
                    str(
                        _Path(
                            doc.metadata.get("source", "")
                            or getattr(doc, "source", "")
                            or getattr(doc, "file_path", "")
                        ).resolve()
                    )
                    for doc in documents
                    if (
                        doc.metadata.get("source")
                        or getattr(doc, "source", "")
                        or getattr(doc, "file_path", "")
                    )
                ]
                # Deduplicate (multiple docs can come from same source file)
                current_file_paths = list(dict.fromkeys(current_file_paths))

                # Invariant: if loader returned documents, we must have paths
                if documents and not current_file_paths:
                    raise RuntimeError(
                        f"Loaded {len(documents)} documents but resolved 0 "
                        f"file paths — metadata['source'] is missing. "
                        f"This is a bug in DocumentLoader."
                    )

                prior_manifest = await self.manifest_tracker.load(abs_folder_path)
                from brainpalace_server.config.indexing_config import (
                    load_indexing_config,
                )

                (
                    eviction_summary,
                    files_to_index_list,
                ) = await eviction_service.compute_diff_and_evict(
                    folder_path=abs_folder_path,
                    current_files=current_file_paths,
                    force=request.force,
                    indexing_config=load_indexing_config(),
                    # Atomic add-then-swap: keep changed files' OLD chunks until
                    # the new ones are upserted, so a crash mid-reindex can't
                    # lose data. The deferred deletes run after the upsert loop
                    # (or in the no-new-docs branch below).
                    defer_changed_eviction=True,
                )
                files_to_index_set = set(files_to_index_list)

                def _resolve_doc_path(doc: Any) -> str:
                    raw = (
                        doc.metadata.get("source", "")
                        or getattr(doc, "source", "")
                        or getattr(doc, "file_path", "")
                    )
                    return str(_Path(raw).resolve()) if raw else ""

                documents = [
                    doc
                    for doc in documents
                    if _resolve_doc_path(doc) in files_to_index_set
                ]
                _deferred = getattr(eviction_summary, "files_deferred", []) or []
                logger.info(
                    f"Manifest diff: +{len(eviction_summary.files_added)} added "
                    f"~{len(eviction_summary.files_changed)} changed "
                    f"-{len(eviction_summary.files_deleted)} deleted "
                    f"={len(eviction_summary.files_unchanged)} unchanged, "
                    f"{eviction_summary.chunks_evicted} chunks evicted"
                    + (
                        f", !{len(_deferred)} deferred (re-embed cooldown)"
                        if _deferred
                        else ""
                    )
                )
                if not documents:
                    # Changed files yielded no new chunks (e.g. emptied/became
                    # unreadable), so there is nothing to swap in — flush their
                    # deferred old-chunk evictions now, before the BM25 rebuild,
                    # so they don't linger as orphans.
                    deferred_ids = list(
                        getattr(eviction_summary, "deferred_evict_ids", []) or []
                    )
                    if deferred_ids:
                        flushed = await self.storage_backend.delete_by_ids(deferred_ids)
                        eviction_summary.chunks_evicted += int(flushed or 0)
                        eviction_summary.deferred_evict_ids = []
                        logger.info(
                            "Flushed %d deferred changed-chunk eviction(s) "
                            "(no replacement chunks produced)",
                            int(flushed or 0),
                        )
                    evicted_only = bool(
                        eviction_summary.files_deleted
                        or eviction_summary.files_changed
                        or eviction_summary.chunks_evicted
                    )
                    if evicted_only:
                        logger.info(
                            "No new files to index, but "
                            f"{eviction_summary.chunks_evicted} chunks evicted "
                            f"(-{len(eviction_summary.files_deleted)} deleted "
                            f"~{len(eviction_summary.files_changed)} changed) — "
                            "rebuilding BM25 from surviving chunks"
                        )
                        # ChromaBackend.delete_by_ids only removes vector-store
                        # chunks; BM25 is a full-rebuild index, so evicted chunks
                        # remain queryable via BM25 until it is rebuilt. Rebuild it
                        # here from the surviving (unchanged) chunks.
                        await self._rebuild_bm25_from_unchanged(
                            prior_manifest, eviction_summary.files_unchanged
                        )
                    else:
                        logger.info("No files need re-indexing - all files unchanged")
                    # Save manifest carrying over ONLY unchanged files — dropping
                    # deleted/changed entries so the derived document count and the
                    # manifest stay consistent with the stores.
                    new_manifest = FolderManifest(folder_path=abs_folder_path)
                    if prior_manifest is not None:
                        assert isinstance(prior_manifest, FolderManifest)
                        # Carry over unchanged AND deferred (Phase L) files: the
                        # deferred record is preserved verbatim (old checksum +
                        # last_embedded_at) so it re-checks the cooldown next run
                        # and its existing chunks stay mapped.
                        for fp in list(eviction_summary.files_unchanged) + list(
                            getattr(eviction_summary, "files_deferred", [])
                        ):
                            if fp in prior_manifest.files:
                                new_manifest.files[fp] = prior_manifest.files[fp]
                    await self.manifest_tracker.save(new_manifest)
                    self._state.status = IndexingStatusEnum.COMPLETED
                    self._state.is_indexing = False
                    self._state.completed_at = datetime.now(timezone.utc)
                    from dataclasses import asdict

                    eviction_summary_result = asdict(eviction_summary)
                    return eviction_summary_result

            if not documents:
                logger.warning(f"No documents found in {request.folder_path}")
                self._state.status = IndexingStatusEnum.COMPLETED
                self._state.is_indexing = False
                self._state.completed_at = datetime.now(timezone.utc)
                return None

            # Step 2: Chunk documents and code files.
            # Report the real document count here so the job's "Files" metric is
            # correct for ALL runs — the code chunker reports no per-file progress,
            # so without this a code-only job would show 0/0. files_processed
            # catches up to files_total at completion.
            if progress_callback:
                await progress_callback(
                    10, 100, "Chunking documents...", 0, len(documents)
                )

            # Separate documents by type
            doc_documents = [
                d for d in documents if d.metadata.get("source_type") == "doc"
            ]
            code_documents = [
                d for d in documents if d.metadata.get("source_type") == "code"
            ]

            logger.info(
                f"Processing {len(doc_documents)} documents and "
                f"{len(code_documents)} code files"
            )

            # Step 2a: Stamp text_language on each document before chunking so
            # every resulting chunk carries the NL code its BM25 analyzer needs.
            # Code chunks always use the "code" analyzer; doc chunks get either
            # the detected language (detect=True) or the project default.
            _bm25_cfg = load_bm25_config()
            if _bm25_cfg.detect:
                from brainpalace_server.indexing.text_analysis.detect import (
                    detect_language,
                )
                from brainpalace_server.indexing.text_analysis.snowball import SNOWBALL

                _allowed: set[str] = set(SNOWBALL) | {"hr"}
                for _d in doc_documents:
                    _d.metadata["text_language"] = detect_language(
                        _d.text,
                        allowed=_allowed,
                        default=_bm25_cfg.language,
                        min_confidence=_bm25_cfg.detect_min_confidence,
                    )
            else:
                for _d in doc_documents:
                    _d.metadata["text_language"] = _bm25_cfg.language
            for _d in code_documents:
                _d.metadata["text_language"] = "code"

            # Step 2a-bis (6.5): stamp the owning folder's domain/authority on
            # every document before chunking, so each resulting chunk inherits
            # them (same plumbing as text_language). authority resolves to a
            # concrete value ('authoritative' by default — decision D); domain
            # is only stamped when the folder carries one.
            _folder_authority = request.authority or "authoritative"
            for _d in documents:
                _d.metadata["authority"] = _folder_authority
                if request.domain:
                    _d.metadata["domain"] = request.domain

            all_chunks: list[TextChunk | CodeChunk] = []
            total_to_process = len(documents)

            # Chunk documents
            doc_chunker = None
            if doc_documents:
                doc_chunker = ContextAwareChunker(
                    chunk_size=request.chunk_size,
                    chunk_overlap=request.chunk_overlap,
                )

                async def doc_chunk_progress(processed: int, total: int) -> None:
                    self._state.processed_documents = processed
                    if progress_callback:
                        pct = 10 + int((processed / total_to_process) * 5)
                        await progress_callback(
                            pct,
                            100,
                            f"Chunking docs: {processed}/{total}",
                            processed,
                            total_to_process,
                        )

                doc_chunks = await doc_chunker.chunk_documents(
                    doc_documents, doc_chunk_progress
                )
                all_chunks.extend(doc_chunks)
                self._total_doc_chunks += len(doc_chunks)
                logger.info(f"Created {len(doc_chunks)} document chunks")

            # Chunk code files
            if code_documents:
                # Group code documents by language for efficient chunking
                code_by_language: dict[str, list[Any]] = {}
                for doc in code_documents:
                    lang = doc.metadata.get("language", "unknown")
                    if lang not in code_by_language:
                        code_by_language[lang] = []
                    code_by_language[lang].append(doc)

                # Track total code documents processed across all languages
                total_code_processed = 0

                for lang, lang_docs in code_by_language.items():
                    if lang == "unknown":
                        logger.warning(
                            f"Skipping {len(lang_docs)} code files with unknown "
                            "language"
                        )
                        continue

                    try:
                        code_chunker = CodeChunker(language=lang)

                        # Create progress callback with fixed offset for this language
                        def make_progress_callback(
                            offset: int,
                        ) -> Callable[[int, int], Awaitable[None]]:
                            async def progress_callback_fn(
                                processed: int,
                                total: int,
                            ) -> None:
                                # processed is relative to current language batch
                                # Convert to total documents processed across
                                # all languages
                                total_processed = offset + processed
                                self._state.processed_documents = total_processed
                                if progress_callback:
                                    pct = 35 + int(
                                        (total_processed / total_to_process) * 15
                                    )
                                    await progress_callback(
                                        pct,
                                        100,
                                        f"Chunking code: {total_processed}/"
                                        f"{total_to_process}",
                                        total_processed,
                                        total_to_process,
                                    )

                            return progress_callback_fn

                        # Calculate offset and create callback for this language batch
                        # Progress callback created but not used in
                        # current implementation
                        # progress_offset = len(doc_documents) + total_code_processed
                        # code_chunk_progress = make_progress_callback(progress_offset)

                        for doc_idx, doc in enumerate(lang_docs):
                            code_chunks = await code_chunker.chunk_code_document(doc)
                            all_chunks.extend(code_chunks)
                            self._total_code_chunks += len(code_chunks)
                            self._supported_languages.add(lang)
                            # Yield to event loop so HTTP requests aren't
                            # starved during long code-chunking runs.
                            if doc_idx % 10 == 0:
                                await asyncio.sleep(0)

                        # Update the total code documents processed
                        total_code_processed += len(lang_docs)

                        chunk_count = sum(
                            1 for c in all_chunks if c.metadata.language == lang
                        )
                        logger.info(f"Created {chunk_count} {lang} chunks")

                    except Exception as e:
                        logger.error(f"Failed to chunk {lang} files: {e}")
                        # Fallback: treat as documents
                        if doc_chunker is not None:  # Reuse doc chunker if available
                            fallback_chunks = await doc_chunker.chunk_documents(
                                lang_docs
                            )
                            all_chunks.extend(fallback_chunks)
                            logger.info(
                                f"Fell back to document chunking for "
                                f"{len(fallback_chunks)} {lang} files"
                            )
                        else:
                            # Create a temporary chunker for fallback
                            fallback_chunker = ContextAwareChunker(
                                chunk_size=request.chunk_size,
                                chunk_overlap=request.chunk_overlap,
                            )
                            fallback_chunks = await fallback_chunker.chunk_documents(
                                lang_docs
                            )
                            all_chunks.extend(fallback_chunks)
                            logger.info(
                                f"Fell back to document chunking for "
                                f"{len(fallback_chunks)} {lang} files"
                            )

            chunks = all_chunks
            self._state.total_chunks = len(chunks)
            logger.info(f"Created {len(chunks)} total chunks")

            # Step 2.5: Apply content injection (INJECT-03, INJECT-07)
            if content_injector is not None:
                known_keys: set[str] = {
                    "chunk_id",
                    "source",
                    "file_name",
                    "chunk_index",
                    "total_chunks",
                    "source_type",
                    "created_at",
                    "language",
                    "text_language",
                    "domain",
                    "authority",
                    "heading_path",
                    "section_title",
                    "content_type",
                    "symbol_name",
                    "symbol_kind",
                    "start_line",
                    "end_line",
                    "docstring",
                    "parameters",
                    "return_type",
                    "decorators",
                    "imports",
                }
                enriched_count = await asyncio.to_thread(
                    content_injector.apply_to_chunks, chunks, known_keys
                )
                logger.info(f"Applied content injection to {enriched_count} chunks")

            # Step 3: Generate embeddings
            if progress_callback:
                await progress_callback(15, 100, "Generating embeddings...")

            # Budget guard: block the job if the to-embed token count exceeds
            # the configured cap (limit<=0 disables; force_budget bypasses).
            # Only cache MISSES count — cached chunks cost no provider call, so
            # a recovery/self-heal reindex whose embeddings all sit in the
            # cache must not be blocked by its raw token size.
            from brainpalace_server.config.indexing_config import (  # noqa: PLC0415
                load_indexing_config as _load_indexing_config,
            )

            _icfg = _load_indexing_config()
            # The FIRST index of a folder is exempt from the budget guard (the
            # adaptive ratio gives a near-empty store ~0 headroom, so the initial
            # index would otherwise trip the bare floor). See _is_initial_index.
            _is_first_index = _is_initial_index(self.manifest_tracker, prior_manifest)
            try:
                _total_chunks = await self.storage_backend.get_count()
            except Exception:  # noqa: BLE001 — cold store → fall back to floor
                _total_chunks = 0
            _budget = effective_token_budget(
                floor=_icfg.max_embed_tokens_per_job,
                ratio=_icfg.max_embed_ratio_per_job,
                total_chunks=_total_chunks,
                chunk_size=request.chunk_size,
            )
            _miss_idx = await self.embedding_generator.uncached_indices(
                [chunk.text for chunk in chunks]
            )
            _tok = enforce_token_budget(
                [chunks[i] for i in _miss_idx],
                limit=_budget,
                force=request.force_budget or _is_first_index,
            )
            if _is_first_index and not request.force_budget and _tok > _budget > 0:
                logger.info(
                    "Initial index of %s — budget guard skipped "
                    "(~%d tokens to embed; %d/%d chunks cached; cap %d)",
                    abs_folder_path,
                    _tok,
                    len(chunks) - len(_miss_idx),
                    len(chunks),
                    _budget,
                )
            else:
                logger.info(
                    "Embedding budget check ok: ~%d tokens to embed "
                    "(%d/%d chunks cached; limit %d)",
                    _tok,
                    len(chunks) - len(_miss_idx),
                    len(chunks),
                    _budget,
                )

            async def embedding_progress(processed: int, total: int) -> None:
                if progress_callback:
                    pct = 15 + int((processed / total) * 35)
                    await progress_callback(pct, 100, f"Embedding: {processed}/{total}")

            # The chunks list mixes prose (TextChunk) and source code
            # (CodeChunk). Meter each under its own usage source ("doc" vs
            # "code") so the dashboard separates real docs from code files,
            # then reassemble the embeddings in the original chunk order.
            from brainpalace_server.indexing.chunking import (
                CodeChunk,
            )  # noqa: PLC0415
            from brainpalace_server.services.usage_metrics import (
                usage_scope,
            )  # noqa: PLC0415

            async def _embed_scoped(group: list[Any], scope: str) -> list[list[float]]:
                if not group:
                    return []
                with usage_scope(scope):
                    return await self.embedding_generator.embed_chunks(
                        group,
                        embedding_progress,
                    )

            _code_chunks = [c for c in chunks if isinstance(c, CodeChunk)]
            _doc_chunks = [c for c in chunks if not isinstance(c, CodeChunk)]
            _doc_emb = await _embed_scoped(_doc_chunks, "doc")
            _code_emb = await _embed_scoped(_code_chunks, "code")

            _di = _ci = 0
            embeddings = []
            for _c in chunks:
                if isinstance(_c, CodeChunk):
                    embeddings.append(_code_emb[_ci])
                    _ci += 1
                else:
                    embeddings.append(_doc_emb[_di])
                    _di += 1
            logger.info(f"Generated {len(embeddings)} embeddings")

            # Step 4: Store in vector database
            if progress_callback:
                await progress_callback(55, 100, "Storing in vector database...")

            # ChromaDB has a max batch size of 41666, so we need to batch our upserts
            # Use a safe batch size of 40000 to leave some margin
            chroma_batch_size = 40000

            for batch_start in range(0, len(chunks), chroma_batch_size):
                batch_end = min(batch_start + chroma_batch_size, len(chunks))
                batch_chunks = chunks[batch_start:batch_end]
                batch_embeddings = embeddings[batch_start:batch_end]

                await self.storage_backend.upsert_documents(
                    ids=[chunk.chunk_id for chunk in batch_chunks],
                    embeddings=batch_embeddings,
                    documents=[chunk.text for chunk in batch_chunks],
                    metadatas=[chunk.metadata.to_dict() for chunk in batch_chunks],
                )

                logger.info(
                    f"Stored batch {batch_start // chroma_batch_size + 1} "
                    f"({len(batch_chunks)} chunks) in vector database"
                )

            # Atomic add-then-swap: the new chunks are now safely upserted, so it
            # is finally safe to delete the CHANGED files' OLD chunks. A crash
            # before this point left the old chunks intact (at worst transient
            # duplicates, reconciled next run) instead of losing data.
            if eviction_summary is not None:
                deferred_id_set = set(
                    getattr(eviction_summary, "deferred_evict_ids", []) or []
                )
                # CRITICAL: a changed file can re-produce byte-identical chunks
                # whose content-hash id is unchanged — those ids were just
                # upserted, so they must NOT be deleted. Only drop old ids that
                # the new chunk set does not re-assert.
                new_ids = {chunk.chunk_id for chunk in chunks}
                to_swap = sorted(deferred_id_set - new_ids)
                if to_swap:
                    swapped = await self.storage_backend.delete_by_ids(to_swap)
                    eviction_summary.chunks_evicted += int(swapped or 0)
                    logger.info(
                        "Atomic swap: deleted %d superseded chunk(s) after the "
                        "new chunks were stored",
                        int(swapped or 0),
                    )
                eviction_summary.deferred_evict_ids = []

            # Store embedding metadata for future validation
            await self.storage_backend.set_embedding_metadata(
                provider=current_provider,
                model=current_model,
                dimensions=current_dimensions,
            )

            # Persist the folder record + manifest NOW — right after the chunks are
            # in the store, BEFORE the rebuildable BM25/graph tail. If the job is
            # interrupted during that slow tail, the store and the manifest stay
            # consistent (document count + watcher intact, next run can diff
            # incrementally); only the derived graph needs a rebuild. Previously
            # this ran at the very end, so an interrupt left orphan chunks with no
            # manifest, no folder record, and a 0-document status.
            eviction_summary_result = await self._persist_index_metadata(
                abs_folder_path=abs_folder_path,
                chunks=chunks,
                request=request,
                prior_manifest=prior_manifest,
                eviction_summary=eviction_summary,
            )

            # Step 5: Build BM25 index
            if progress_callback:
                await progress_callback(60, 100, "Building BM25 index...")

            nodes = [
                TextNode(
                    text=chunk.text,
                    id_=chunk.chunk_id,
                    metadata=chunk.metadata.to_dict(),
                )
                for chunk in chunks
            ]
            # BM25 index build is CPU-heavy (tokenization + scoring).
            # Run in a thread so the event loop stays responsive.
            # When chunks (and therefore nodes) is empty — e.g. all new files
            # were empty placeholders — bm25_index.build_index treats it as
            # a no-op rather than raising. Issue #143.
            bm25_mgr = self.bm25_manager
            await asyncio.to_thread(bm25_mgr.build_index, nodes)

            # For incremental runs, BM25 must include unchanged file chunks too —
            # and deferred (Phase L) files, whose chunks also survived eviction.
            _survivors = (
                list(eviction_summary.files_unchanged)
                + list(getattr(eviction_summary, "files_deferred", []))
                if eviction_summary is not None
                else []
            )
            if (
                eviction_summary is not None
                and _survivors
                and self.manifest_tracker is not None
                and prior_manifest is not None
            ):
                from brainpalace_server.services.manifest_tracker import FolderManifest

                assert isinstance(prior_manifest, FolderManifest)
                # Collect surviving chunk IDs (unchanged + deferred) from prior
                unchanged_ids = []
                for fp in _survivors:
                    if fp in prior_manifest.files:
                        unchanged_ids.extend(prior_manifest.files[fp].chunk_ids)
                if unchanged_ids:
                    unchanged_nodes = []
                    for chunk_id in unchanged_ids:
                        try:
                            result = await self.storage_backend.get_by_id(chunk_id)
                            if result:
                                node = TextNode(
                                    id_=chunk_id,
                                    text=result.get("text", ""),
                                    metadata=result.get("metadata", {}),
                                )
                                unchanged_nodes.append(node)
                        except Exception as bm25_e:
                            logger.warning(
                                f"Could not fetch chunk {chunk_id} for BM25: {bm25_e}"
                            )
                    if unchanged_nodes:
                        all_bm25_nodes = nodes + unchanged_nodes
                        bm25_mgr2 = getattr(self.storage_backend, "bm25_manager", None)
                        if bm25_mgr2 is not None:
                            await asyncio.to_thread(
                                bm25_mgr2.build_index, all_bm25_nodes
                            )
                            logger.info(
                                f"BM25 rebuilt with {len(all_bm25_nodes)} total "
                                "nodes (incremental)"
                            )
                        else:
                            await asyncio.to_thread(
                                self.bm25_manager.build_index, all_bm25_nodes
                            )
                            logger.info(
                                f"BM25 rebuilt with {len(all_bm25_nodes)} total "
                                "nodes (incremental, fallback)"
                            )

            # Step 6: Build graph index if enabled (Feature 113)
            if settings.ENABLE_GRAPH_INDEX:
                if progress_callback:
                    await progress_callback(65, 100, "Building graph index...")

                # Graph build runs in a worker thread and emits per-doc
                # progress; mirror it onto the job via a tiny poller on the
                # loop (avoids cross-thread coroutine scheduling). Band 65..99.
                graph_state = {"current": 0, "total": 1}

                def graph_progress(current: int, total: int, message: str) -> None:
                    graph_state["current"] = current
                    graph_state["total"] = total

                graph_mgr = self.graph_index_manager
                gstore = self.graph_index_manager.graph_store
                _did_identity_clear = False
                _did_corpus_rebuild = False
                if gstore.needs_code_identity_rebuild():
                    if request.force:
                        gstore.clear()
                        _did_identity_clear = True
                    else:
                        # One-time identity migration (spec §Migration): promote
                        # this run to a full rebuild from the corpus so no
                        # manual --force is ever required. Best-effort: on
                        # failure the incremental build below still runs.
                        try:
                            rebuilt = await self.rebuild_graph_from_corpus(
                                request.folder_path
                            )
                            _did_corpus_rebuild = rebuilt > 0
                            if _did_corpus_rebuild:
                                logger.info(
                                    "One-time graph identity rebuild: "
                                    f"{rebuilt} triplets"
                                )
                        except Exception:
                            logger.warning(
                                "identity rebuild failed; continuing with "
                                "incremental graph build",
                                exc_info=True,
                            )

                def _build_graph() -> int:
                    return graph_mgr.build_from_documents(
                        chunks,
                        progress_callback=graph_progress,
                        root=os.path.abspath(request.folder_path),
                    )

                async def _poll_graph_progress() -> None:
                    last: tuple[int, int] | None = None
                    while True:
                        c = graph_state["current"]
                        t = max(graph_state["total"], 1)
                        if progress_callback and (c, t) != last:
                            last = (c, t)
                            pct = 65 + int((c / t) * 34)
                            await progress_callback(
                                min(pct, 99), 100, f"Building graph index: {c}/{t}"
                            )
                        await asyncio.sleep(0.5)

                if _did_corpus_rebuild:
                    triplet_count = 0  # corpus rebuild covered this run
                else:
                    poller = asyncio.create_task(_poll_graph_progress())
                    try:
                        triplet_count = await asyncio.to_thread(_build_graph)
                    finally:
                        poller.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await poller
                logger.info(f"Graph index built with {triplet_count} triplets")
                if _did_identity_clear:
                    gstore.mark_code_identity_rebuilt()

            # Mark as completed
            self._state.status = IndexingStatusEnum.COMPLETED
            self._state.completed_at = datetime.now(timezone.utc)
            self._state.is_indexing = False
            self._indexed_folders.add(abs_folder_path)

            if progress_callback:
                await progress_callback(100, 100, "Indexing complete!")

            logger.info(
                f"Indexing job {job_id} completed: "
                f"{len(documents)} docs, {len(chunks)} chunks"
            )

            return eviction_summary_result

        except Exception as e:
            logger.error(f"Indexing job {job_id} failed: {e}")
            self._state.status = IndexingStatusEnum.FAILED
            self._state.error = str(e)
            self._state.is_indexing = False
            raise

        finally:
            self._state.is_indexing = False

    async def _persist_index_metadata(
        self,
        abs_folder_path: str,
        chunks: list[Any],
        request: Any,
        prior_manifest: Any,
        eviction_summary: Any,
    ) -> dict[str, Any] | None:
        """Persist the folder record + manifest once chunks are in the store.

        Called immediately after the chunk upsert and BEFORE the rebuildable BM25
        and graph steps, so the vector store and the manifest stay consistent even
        if the job is interrupted during that slow tail: the stored chunks are
        mapped by a saved manifest (document count + watcher stay correct, the next
        run can diff incrementally) and only the derived graph needs a rebuild.
        Previously this ran at the very end, so an interrupt left orphan chunks with
        no manifest, no folder record, and a 0-document status.

        Returns the eviction-summary dict for the index result, or None.
        """
        # Save manifest once chunks are stored (Phase 14). This per-file manifest
        # is the source of truth for what the folder currently owns, so it is
        # built FIRST and the folder-level chunk_ids are derived from it below.
        eviction_summary_result: dict[str, Any] | None = None
        new_manifest: Any = None
        if self.manifest_tracker is not None and eviction_summary is not None:
            import os as _os
            import time as _time
            from dataclasses import asdict
            from pathlib import Path as _Path

            from brainpalace_server.services.manifest_tracker import (
                FileRecord,
                FolderManifest,
                compute_file_checksum,
            )

            new_manifest = FolderManifest(folder_path=abs_folder_path)
            # Carry over unchanged AND deferred (Phase L) files. Deferred records
            # are preserved verbatim (old checksum + last_embedded_at) so the file
            # re-checks the re-embed cooldown next run and keeps its mapped chunks.
            if prior_manifest is not None:
                assert isinstance(prior_manifest, FolderManifest)
                for fp in list(eviction_summary.files_unchanged) + list(
                    getattr(eviction_summary, "files_deferred", [])
                ):
                    if fp in prior_manifest.files:
                        new_manifest.files[fp] = prior_manifest.files[fp]
            # Record newly indexed files (stamp Phase L embed metadata)
            embedded_at = _time.time()
            file_to_chunks: dict[str, list[str]] = {}
            for chunk in chunks:
                src = chunk.metadata.to_dict().get("source", "")
                if src:
                    resolved_src = str(_Path(src).resolve())
                    file_to_chunks.setdefault(resolved_src, []).append(chunk.chunk_id)
            for fp, chunk_ids in file_to_chunks.items():
                checksum = await asyncio.to_thread(compute_file_checksum, fp)
                stat_result = await asyncio.to_thread(_os.stat, fp)
                new_manifest.files[fp] = FileRecord(
                    checksum=checksum,
                    mtime=stat_result.st_mtime,
                    chunk_ids=chunk_ids,
                    last_embedded_at=embedded_at,
                    size_bytes=getattr(stat_result, "st_size", 0),
                )
            # Record added/changed files that produced ZERO chunks (e.g. an empty
            # __init__.py) with an empty chunk_ids list. Without a record they are
            # never tracked, so every subsequent scan re-classifies them as "added"
            # and re-indexes them — an endless no-op churn that schedules watch
            # jobs creating no chunks. An empty-chunk record is safe: reconcile
            # skips it (`if frec.chunk_ids`) and the folder chunk-id set ignores it.
            for fp in list(eviction_summary.files_added) + list(
                eviction_summary.files_changed
            ):
                rfp = str(_Path(fp).resolve())
                if rfp in new_manifest.files:
                    continue
                try:
                    checksum = await asyncio.to_thread(compute_file_checksum, rfp)
                    stat_result = await asyncio.to_thread(_os.stat, rfp)
                except OSError:
                    # File vanished between scan and persist — skip; the next
                    # run's diff will treat it as deleted.
                    continue
                new_manifest.files[rfp] = FileRecord(
                    checksum=checksum,
                    mtime=stat_result.st_mtime,
                    chunk_ids=[],
                    last_embedded_at=embedded_at,
                    size_bytes=getattr(stat_result, "st_size", 0),
                )
            await self.manifest_tracker.save(new_manifest)
            logger.info(f"Manifest saved with {len(new_manifest.files)} file entries")
            eviction_summary_result = asdict(eviction_summary)

        # Register folder with FolderManager for persistent tracking (Phase 12).
        # The folder's chunk_ids are the authoritative set derived from the
        # current per-file manifest (retains unchanged files, drops deleted ones)
        # so the persisted chunk_count self-heals instead of growing forever.
        if self.folder_manager is not None:
            if new_manifest is not None:
                folder_chunk_ids = _folder_chunk_ids(new_manifest)
            else:
                # No incremental tracking (full index without manifest): this
                # run's chunks are the complete set.
                folder_chunk_ids = sorted({chunk.chunk_id for chunk in chunks})
            existing = await self.folder_manager.get_folder(abs_folder_path)
            watch_mode, watch_debounce_seconds = _resolve_watch_settings(
                has_existing=existing is not None,
                existing_watch_mode=existing.watch_mode if existing else None,
                existing_debounce=(
                    existing.watch_debounce_seconds if existing else None
                ),
                request_watch_mode=request.watch_mode,
                request_debounce=request.watch_debounce_seconds,
            )
            await self.folder_manager.add_folder(
                folder_path=abs_folder_path,
                chunk_count=len(folder_chunk_ids),
                chunk_ids=folder_chunk_ids,
                watch_mode=watch_mode,
                watch_debounce_seconds=watch_debounce_seconds,
                include_code=request.include_code,
                source=request.trigger,
                domain=request.domain,
                authority=request.authority or "authoritative",
            )

        return eviction_summary_result

    async def _rebuild_bm25_from_unchanged(
        self,
        prior_manifest: Any,
        files_unchanged: list[str],
    ) -> None:
        """Rebuild the BM25 index from surviving (unchanged) chunks after eviction.

        ChromaBackend.delete_by_ids removes chunks only from the vector store;
        BM25 is a full-rebuild structure with no per-id deletion, so evicted
        chunks remain queryable via BM25 until it is rebuilt. This is invoked on
        the "no new documents but chunks were evicted" path (e.g. a pure delete)
        so deleted/changed chunks stop surfacing in keyword search.

        Args:
            prior_manifest: Prior FolderManifest (or None) holding chunk IDs.
            files_unchanged: Paths whose chunks survive and must be retained.
        """
        from brainpalace_server.services.manifest_tracker import FolderManifest

        survivors: list[TextNode] = []
        if prior_manifest is not None:
            assert isinstance(prior_manifest, FolderManifest)
            unchanged_ids: list[str] = []
            for fp in files_unchanged:
                if fp in prior_manifest.files:
                    unchanged_ids.extend(prior_manifest.files[fp].chunk_ids)
            for chunk_id in unchanged_ids:
                try:
                    result = await self.storage_backend.get_by_id(chunk_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        f"Could not fetch chunk {chunk_id} for BM25 rebuild: {exc}"
                    )
                    continue
                if result:
                    survivors.append(
                        TextNode(
                            id_=chunk_id,
                            text=result.get("text", ""),
                            metadata=result.get("metadata", {}),
                        )
                    )

        bm25_mgr = getattr(self.storage_backend, "bm25_manager", None)
        if bm25_mgr is None:
            bm25_mgr = self.bm25_manager

        if survivors:
            await asyncio.to_thread(bm25_mgr.build_index, survivors)
            logger.info(
                f"BM25 rebuilt with {len(survivors)} surviving node(s) after eviction"
            )
        else:
            # build_index([]) is a no-op by design (issue #143), so reset to
            # ensure evicted chunks are not left queryable when nothing survives.
            await asyncio.to_thread(bm25_mgr.reset)
            logger.info("BM25 reset after eviction left no surviving chunks")

    async def get_document_count(self) -> int:
        """Distinct indexed documents derived from persisted manifests.

        Authoritative count derived from the per-folder manifests (distinct
        indexed file paths) rather than the ephemeral in-process state, which
        is only updated when a full index runs in this process — async jobs
        run in the worker and never touch it. Falls back to the last-known
        state value when manifests are unavailable.
        """
        if self.folder_manager is None or self.manifest_tracker is None:
            return self._state.total_documents
        try:
            paths: set[str] = set()
            for folder in await self.folder_manager.list_folders():
                manifest = await self.manifest_tracker.load(folder.folder_path)
                if manifest is not None:
                    paths.update(manifest.files.keys())
            return len(paths)
        except Exception:  # noqa: BLE001 — never fail /status on the count
            return self._state.total_documents

    async def get_document_counts_by_type(self) -> dict[str, int]:
        """Durable code/doc/total document counts from persisted manifests.

        Mirrors get_document_count (manifest-derived, survives restart) but
        splits the distinct file paths by extension. Falls back to a single
        total bucket when manifests are unavailable.
        """
        if self.folder_manager is None or self.manifest_tracker is None:
            total = self._state.total_documents
            return {"code": 0, "doc": 0, "total": total}
        try:
            paths: set[str] = set()
            for folder in await self.folder_manager.list_folders():
                manifest = await self.manifest_tracker.load(folder.folder_path)
                if manifest is not None:
                    paths.update(manifest.files.keys())
        except Exception:  # noqa: BLE001 — never fail /status on the count
            return {"code": 0, "doc": 0, "total": self._state.total_documents}
        return _classify_documents(paths)

    async def rebuild_graph_from_corpus(self, folder_path: str | None = None) -> int:
        """Clear + rebuild the graph from the already-indexed corpus.

        Reads all chunks from the BM25 corpus (text + metadata), clears the
        graph, and rebuilds with canonical identity. Marks the one-time
        identity flag on success. Returns the triplet count (0 when the corpus
        is empty — flag stays pending).
        """
        bm25 = self.bm25_manager
        if not bm25.is_initialized:
            bm25.initialize()
        nodes = bm25.all_nodes()
        if not nodes:
            return 0
        # Callers that omit folder_path (e.g. the dashboard button) still need a
        # workspace root so LSP resolves cross-file targets — fall back to the
        # first indexed folder.
        if not folder_path and self.folder_manager is not None:
            try:
                folder_records = await self.folder_manager.list_folders()
                if folder_records:
                    folder_path = folder_records[0].folder_path
            except Exception:  # noqa: BLE001 — best-effort root derivation
                folder_path = None
        graph_mgr = self.graph_index_manager
        graph_mgr.clear()
        graph_mgr.graph_store.initialize()
        root = os.path.abspath(folder_path) if folder_path else None
        count: int = await asyncio.to_thread(
            graph_mgr.build_from_documents, nodes, None, root
        )
        graph_mgr.graph_store.mark_code_identity_rebuilt()
        logger.info("Graph rebuilt from corpus: %d triplets", count)
        return count

    def _graph_needs_identity_rebuild(self) -> bool:
        """True while the one-time canonical-identity rebuild is pending."""
        try:
            return bool(
                self.graph_index_manager.graph_store.needs_code_identity_rebuild()
            )
        except Exception:  # noqa: BLE001 — status is best-effort
            return False

    async def get_status(self) -> dict[str, Any]:
        """
        Get current indexing status.

        Returns:
            Dictionary with status information.
        """
        total_chunks = (
            await self.storage_backend.get_count()
            if self.storage_backend.is_initialized
            else 0
        )

        # Use the instance variables we've been tracking during indexing
        total_doc_chunks = self._total_doc_chunks
        total_code_chunks = self._total_code_chunks
        supported_languages = sorted(self._supported_languages)

        # Get graph index status (Feature 113)
        graph_status = self.graph_index_manager.get_status()

        # Use FolderManager for persistent folder list if available (Phase 12)
        if self.folder_manager is not None:
            folder_records = await self.folder_manager.list_folders()
            indexed_folders: list[str] = [r.folder_path for r in folder_records]
        else:
            indexed_folders = sorted(self._indexed_folders)

        return {
            "status": self._state.status.value,
            "is_indexing": self._state.is_indexing,
            "current_job_id": self._state.current_job_id,
            "folder_path": self._state.folder_path,
            "total_documents": self._state.total_documents,
            "processed_documents": self._state.processed_documents,
            "total_chunks": total_chunks,
            "total_doc_chunks": total_doc_chunks,
            "total_code_chunks": total_code_chunks,
            "supported_languages": supported_languages,
            "progress_percent": self._state.progress_percent,
            "started_at": (
                self._state.started_at.isoformat() if self._state.started_at else None
            ),
            "completed_at": (
                self._state.completed_at.isoformat()
                if self._state.completed_at
                else None
            ),
            "error": self._state.error,
            "indexed_folders": indexed_folders,
            # Graph index status (Feature 113)
            "graph_index": {
                "enabled": graph_status.enabled,
                "initialized": graph_status.initialized,
                "entity_count": graph_status.entity_count,
                "relationship_count": graph_status.relationship_count,
                "store_type": graph_status.store_type,
                "needs_identity_rebuild": self._graph_needs_identity_rebuild(),
            },
        }

    async def reset(self) -> None:
        """Reset the indexing service and vector store.

        Note: Embedding metadata is stored in collection metadata,
        so it will be cleared when collection is reset.
        """
        async with self._lock:
            await self.vector_store.reset()
            self.bm25_manager.reset()
            # Clear graph index (Feature 113)
            self.graph_index_manager.clear()
            # Clear folder manager records (Phase 12)
            if self.folder_manager is not None:
                await self.folder_manager.clear()
            # Purge per-folder manifests so a subsequent re-index does not read
            # a stale manifest and skip every file as "unchanged" while the
            # stores are empty (manifest/reset desync bug).
            if self.manifest_tracker is not None:
                await self.manifest_tracker.delete_all()
            self._state = IndexingState(
                current_job_id="",
                folder_path="",
                started_at=None,
                completed_at=None,
                error=None,
            )
            self._indexed_folders.clear()
            self._total_doc_chunks = 0
            self._total_code_chunks = 0
            self._supported_languages.clear()
            logger.info("Indexing service reset")


# Singleton instance
_indexing_service: IndexingService | None = None


def get_indexing_service() -> IndexingService:
    """Get the global indexing service instance."""
    global _indexing_service
    if _indexing_service is None:
        _indexing_service = IndexingService()
    return _indexing_service

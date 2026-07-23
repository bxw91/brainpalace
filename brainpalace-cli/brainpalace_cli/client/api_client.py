"""HTTP client for Doc-Serve API communication."""

from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

import httpx


class DocServeError(Exception):
    """Base exception for Doc-Serve client errors."""

    pass


class ConnectionError(DocServeError):
    """Raised when unable to connect to the server."""

    pass


class ServerError(DocServeError):
    """Raised when server returns an error response."""

    def __init__(self, message: str, status_code: int, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass
class HealthStatus:
    """Server health status."""

    status: str
    message: str | None
    version: str
    timestamp: str


@dataclass
class IndexingStatus:
    """Detailed indexing status."""

    total_documents: int
    total_chunks: int
    indexing_in_progress: bool
    current_job_id: str | None
    progress_percent: float
    last_indexed_at: str | None
    indexed_folders: list[str]
    code_documents: int = 0
    doc_documents: int = 0
    code_chunks: int = 0
    doc_chunks: int = 0
    file_watcher: dict[str, Any] | None = None
    embedding_cache: dict[str, Any] | None = None
    migration: dict[str, Any] | None = None
    graph_index: dict[str, Any] | None = None
    features: dict[str, Any] | None = None
    #: Programmatic text-ingest chunk count block ({"chunks": int}); separate
    #: from folder-manifest-derived total_documents (spec Item 3).
    text_ingest: dict[str, Any] | None = None
    #: Index-drift warnings (embedding provider/model or storage backend changed
    #: away from what the existing index was built with). Empty when consistent.
    index_warnings: list[str] = field(default_factory=list)
    #: Presentation-neutral status report — the single source `bp status` and
    #: the dashboard Status tab both render (see
    #: brainpalace_server.status_report). {"rows": [{key,label,value,tone}],
    #: "alerts": [{kind,severity,title,lines,action}]}
    report: dict[str, Any] | None = None


@dataclass
class QueryResult:
    """Single query result."""

    text: str
    source: str
    score: float
    chunk_id: str
    metadata: dict[str, Any]
    vector_score: float | None = None
    bm25_score: float | None = None


@dataclass
class ComputeRow:
    """One compute-mode aggregation row."""

    label: str
    value: float
    metric: str
    op: str
    group: str | None = None
    unit: str | None = None
    score: float = 0.0


@dataclass
class ScanRow:
    """One scan-mode row (term count per bucket)."""

    label: str
    value: float
    term: str
    group: str | None = None
    score: float = 0.0


@dataclass
class AbsenceRow:
    """One absence-mode row (subject present under one partition, absent under
    another)."""

    label: str
    present_in: str
    absent_from: str
    partition: str
    score: float = 0.0


@dataclass
class TimelineRow:
    """One timeline-mode row (an entity's edge at a point in its history)."""

    subject: str
    predicate: str
    object: str
    valid_from: str | None = None
    valid_until: str | None = None
    valid: bool = True
    score: float = 0.0


@dataclass
class QueryResponse:
    """Query response with results."""

    results: list[QueryResult]
    query_time_ms: float
    total_results: int
    compute: list[ComputeRow] | None = None
    scan: list[ScanRow] | None = None
    absence: list[AbsenceRow] | None = None
    timeline: list[TimelineRow] | None = None
    index_blocked: dict[str, Any] | None = None
    #: Set when the server executed a DIFFERENT mode than the one requested
    #: (auto-router re-route, or a read-only degrade to bm25). None otherwise.
    routed_mode: str | None = None


@dataclass
class FolderInfo:
    """Indexed folder information."""

    folder_path: str
    chunk_count: int
    last_indexed: str
    watch_mode: str = "off"
    watch_debounce_seconds: int | None = None


@dataclass
class IndexResponse:
    """Indexing operation response."""

    job_id: str
    status: str
    message: str | None


class DocServeClient:
    """HTTP client for Doc-Serve API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
    ):
        """
        Initialize the client.

        Args:
            base_url: Server base URL.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> "DocServeClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the server.

        Args:
            method: HTTP method (GET, POST, DELETE).
            path: API path.
            json: Optional JSON body.
            params: Optional query parameters.

        Returns:
            Response JSON data.

        Raises:
            ConnectionError: If unable to connect.
            ServerError: If server returns an error.
        """
        url = f"{self.base_url}{path}"

        try:
            response = self._client.request(method, url, json=json, params=params)
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Unable to connect to server at {self.base_url}. "
                f"Is the server running? Error: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise ConnectionError(
                f"Request timed out after {self.timeout}s. "
                "The server may be overloaded or unresponsive."
            ) from e

        if response.status_code >= 400:
            detail = None
            try:
                error_data = response.json()
                detail = error_data.get("detail", str(error_data))
            except Exception:
                detail = response.text

            raise ServerError(
                f"Server returned {response.status_code}",
                status_code=response.status_code,
                detail=detail,
            )

        result: dict[str, Any] = response.json()
        return result

    def health(self) -> HealthStatus:
        """
        Get server health status.

        Returns:
            HealthStatus with current status.
        """
        data = self._request("GET", "/health/")
        return HealthStatus(
            status=data["status"],
            message=data.get("message"),
            version=data.get("version", "unknown"),
            timestamp=data.get("timestamp", ""),
        )

    def rehome_status(self) -> dict[str, Any]:
        """GET /rehome/ — rehome/quarantine status (served even when quarantined)."""
        return self._request("GET", "/rehome/")

    def rehome_resume(self) -> dict[str, Any]:
        """POST /rehome/resume — resume a pending/failed rehome from its checkpoint.

        Raises ``ServerError`` (409) when there is nothing to resume.
        """
        return self._request("POST", "/rehome/resume")

    def status(self) -> IndexingStatus:
        """
        Get detailed indexing status.

        Returns:
            IndexingStatus with document counts and progress.
        """
        data = self._request("GET", "/health/status")
        return IndexingStatus(
            total_documents=data.get("total_documents", 0),
            total_chunks=data.get("total_chunks", 0),
            code_documents=data.get("code_documents", 0),
            doc_documents=data.get("doc_documents", 0),
            code_chunks=data.get("total_code_chunks", 0),
            doc_chunks=data.get("total_doc_chunks", 0),
            indexing_in_progress=data.get("indexing_in_progress", False),
            current_job_id=data.get("current_job_id"),
            progress_percent=data.get("progress_percent", 0.0),
            last_indexed_at=data.get("last_indexed_at"),
            indexed_folders=data.get("indexed_folders", []),
            file_watcher=data.get("file_watcher"),
            embedding_cache=data.get("embedding_cache"),
            graph_index=data.get("graph_index"),
            features=data.get("features"),
            text_ingest=data.get("text_ingest"),
            index_warnings=data.get("index_warnings") or [],
            report=data.get("report"),
        )

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
        mode: str = "hybrid",
        alpha: float = 0.5,
        source_types: list[str] | None = None,
        languages: list[str] | None = None,
        file_paths: list[str] | None = None,
        domains: list[str] | None = None,
        metadata_filter: dict[str, str] | None = None,
        time_decay: bool = True,
        language: str | None = None,
        include_sensitive: bool = False,
        entity_types: list[str] | None = None,
        relationship_types: list[str] | None = None,
    ) -> QueryResponse:
        """
        Query indexed documents.

        Args:
            query_text: Search query.
            top_k: Number of results to return.
            similarity_threshold: Minimum similarity score.
            mode: Retrieval mode (vector, bm25, hybrid).
            alpha: Hybrid search weighting (1.0=vector, 0.0=bm25).
            source_types: Filter by source types (doc, code, test).
            languages: Filter by programming languages.
            file_paths: Filter by file path patterns.
            domains: Filter to chunks ingested under one of these domains
                (reserved `domain` metadata key; OR across values).
            metadata_filter: Filter to chunks whose metadata exact-matches
                every key/value pair (AND across keys).
            language: BM25 query language override (ISO 639-1). Defaults to
                the project bm25.language setting when None.
            include_sensitive: Reveal rows marked sensitive (interactive CLI
                only). Omitted from the request when False, so MCP/dashboard
                callers — which never pass it — stay at default-deny.
            entity_types: Filter graph results by entity types (e.g. ["Class",
                "Function"]). Only applies to graph/multi modes.
            relationship_types: Filter graph results by relationship types
                (e.g. ["calls", "extends"]). Only applies to graph/multi modes.

        Returns:
            QueryResponse with matching results.
        """
        request_data = {
            "query": query_text,
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "mode": mode,
            "alpha": alpha,
        }
        if not time_decay:
            request_data["time_decay"] = False
        if include_sensitive:
            request_data["include_sensitive"] = True
        # Truthy (not ``is not None``) so an empty list means "no filter" — the
        # MCP QueryInput now defaults these to ``[]`` (avoids a nullable-union
        # JSON schema that some LLM clients mishandle). Empty == omit == default.
        if source_types:
            request_data["source_types"] = source_types
        if languages:
            request_data["languages"] = languages
        if file_paths:
            request_data["file_paths"] = file_paths
        if domains:
            request_data["domains"] = domains
        if metadata_filter:
            request_data["metadata_filter"] = metadata_filter
        if language is not None:
            request_data["language"] = language
        if entity_types:
            request_data["entity_types"] = entity_types
        if relationship_types:
            request_data["relationship_types"] = relationship_types

        data = self._request("POST", "/query/", json=request_data)

        results = [
            QueryResult(
                text=r["text"],
                source=r["source"],
                score=r["score"],
                chunk_id=r["chunk_id"],
                metadata=r.get("metadata", {}),
                vector_score=r.get("vector_score"),
                bm25_score=r.get("bm25_score"),
            )
            for r in data.get("results", [])
        ]

        raw_compute = data.get("compute")
        compute_rows: list[ComputeRow] | None = None
        if raw_compute is not None:
            compute_rows = [
                ComputeRow(
                    label=c["label"],
                    value=c["value"],
                    metric=c["metric"],
                    op=c["op"],
                    group=c.get("group"),
                    unit=c.get("unit"),
                    score=c.get("score", 0.0),
                )
                for c in raw_compute
            ]

        raw_scan = data.get("scan")
        scan_rows: list[ScanRow] | None = None
        if raw_scan is not None:
            scan_rows = [
                ScanRow(
                    label=str(r.get("label", "")),
                    value=float(r.get("value", 0.0)),
                    term=str(r.get("term", "")),
                    group=r.get("group"),
                    score=float(r.get("score", 0.0)),
                )
                for r in raw_scan
            ]

        raw_absence = data.get("absence")
        absence_rows: list[AbsenceRow] | None = None
        if raw_absence is not None:
            absence_rows = [
                AbsenceRow(
                    label=str(r.get("label", "")),
                    present_in=str(r.get("present_in", "")),
                    absent_from=str(r.get("absent_from", "")),
                    partition=str(r.get("partition", "")),
                    score=float(r.get("score", 0.0)),
                )
                for r in raw_absence
            ]

        raw_timeline = data.get("timeline")
        timeline_rows: list[TimelineRow] | None = None
        if raw_timeline is not None:
            timeline_rows = [
                TimelineRow(
                    subject=str(r.get("subject", "")),
                    predicate=str(r.get("predicate", "")),
                    object=str(r.get("object", "")),
                    valid_from=r.get("valid_from"),
                    valid_until=r.get("valid_until"),
                    valid=bool(r.get("valid", r.get("valid_until") is None)),
                    score=float(r.get("score", 0.0)),
                )
                for r in raw_timeline
            ]

        return QueryResponse(
            results=results,
            query_time_ms=data.get("query_time_ms", 0.0),
            total_results=data.get("total_results", len(results)),
            compute=compute_rows,
            scan=scan_rows,
            absence=absence_rows,
            timeline=timeline_rows,
            index_blocked=data.get("index_blocked"),
            routed_mode=data.get("routed_mode"),
        )

    def index(
        self,
        folder_path: str,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        recursive: bool = True,
        include_code: bool = False,
        supported_languages: list[str] | None = None,
        code_chunk_strategy: str = "ast_aware",
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        include_types: list[str] | None = None,
        force: bool = False,
        force_budget: bool = False,
        allow_external: bool = False,
        injector_script: str | None = None,
        folder_metadata_file: str | None = None,
        dry_run: bool = False,
        watch_mode: str | None = None,
        watch_debounce_seconds: int | None = None,
        rebuild_graph: bool = False,
        domain: str | None = None,
        authority: str | None = None,
        force_authority: bool = False,
    ) -> IndexResponse:
        """
        Enqueue an indexing job for documents and optionally code from a folder.

        Args:
            folder_path: Path to folder with documents.
            chunk_size: Target chunk size in tokens.
            chunk_overlap: Overlap between chunks.
            recursive: Whether to scan recursively.
            include_code: Whether to index source code files.
            supported_languages: Languages to index (defaults to all).
            code_chunk_strategy: Strategy for code chunking.
            include_patterns: Additional include patterns.
            exclude_patterns: Additional exclude patterns.
            include_types: File type preset names (e.g., ["python", "docs"]).
            force: Bypass deduplication and force a new job.
            force_budget: Bypass the per-job embedding-token budget guard.
            allow_external: Allow paths outside the project directory.
            injector_script: Path to Python script exporting process_chunk().
            folder_metadata_file: Path to JSON file with static metadata.
            dry_run: Validate injector against sample chunks without indexing.
            watch_mode: Watch mode for auto-reindex: 'auto' or 'off'.
            watch_debounce_seconds: Per-folder debounce in seconds.
            rebuild_graph: Rebuild the graph index from existing chunks only
                (no embedding); returns a completed response, not a queued job.
            domain: Optional user-facing domain label for the folder (6.5).
            authority: Binary provenance trust level: 'authoritative' or
                'reference' (6.5). None lets the server resolve the default.
            force_authority: Allow an external folder to be registered as
                'authoritative' (6.5).

        Returns:
            IndexResponse with job ID and queue status.
        """
        body: dict[str, Any] = {
            "folder_path": folder_path,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "recursive": recursive,
            "include_code": include_code,
            "supported_languages": supported_languages,
            "code_chunk_strategy": code_chunk_strategy,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "force": force,
            "force_budget": force_budget,
            "force_authority": force_authority,
        }
        if domain is not None:
            body["domain"] = domain
        if authority is not None:
            body["authority"] = authority
        if include_types is not None:
            body["include_types"] = include_types
        if injector_script is not None:
            body["injector_script"] = injector_script
        if folder_metadata_file is not None:
            body["folder_metadata_file"] = folder_metadata_file
        if dry_run:
            body["dry_run"] = True
        if watch_mode is not None:
            body["watch_mode"] = watch_mode
        if watch_debounce_seconds is not None:
            body["watch_debounce_seconds"] = watch_debounce_seconds

        data = self._request(
            "POST",
            "/index/",
            json=body,
            params={
                "force": force,
                "allow_external": allow_external,
                "rebuild_graph": rebuild_graph,
            },
        )

        return IndexResponse(
            job_id=data["job_id"],
            status=data["status"],
            message=data.get("message"),
        )

    def ingest_text(
        self,
        *,
        items: list[dict[str, Any]],
        sensitivity: str = "normal",
        language: str | None = None,
    ) -> dict[str, Any]:
        """
        Ingest free text with caller-supplied provenance (spec Item 3).

        Args:
            items: List of {text, metadata, domain, source, source_id} dicts.
            sensitivity: Sensitivity mark applied to all items in this call.
            language: Optional BM25 language override.

        Returns:
            Response dict with chunks_new, chunks_kept, chunks_deleted,
            chunk_ids, source_ids.
        """
        body: dict[str, Any] = {"items": items, "sensitivity": sensitivity}
        if language:
            body["language"] = language
        return self._request("POST", "/ingest/text", json=body)

    def ingest_records(
        self,
        *,
        items: list[dict[str, Any]],
        sensitivity: str = "normal",
    ) -> dict[str, Any]:
        """Ingest caller-asserted typed records (POST /ingest/records).

        Args:
            items: List of {subject, metric, value, unit?, ts?, domain, source,
                source_id, confidence?, properties?} dicts.
            sensitivity: Sensitivity mark applied to all items in this call.

        Returns:
            Response dict with the number of records persisted.
        """
        return self._request(
            "POST",
            "/ingest/records",
            json={"items": items, "sensitivity": sensitivity},
        )

    def ingest_references(
        self,
        *,
        items: list[dict[str, Any]],
        sensitivity: str = "normal",
    ) -> dict[str, Any]:
        """Ingest lazy-tier references (POST /ingest/references).

        Args:
            items: List of {pointer, summary, domain, source, source_id} dicts.
            sensitivity: Sensitivity mark applied to all items in this call.

        Returns:
            Response dict with the number of references persisted.
        """
        return self._request(
            "POST",
            "/ingest/references",
            json={"items": items, "sensitivity": sensitivity},
        )

    def references_list(self, domain: str | None = None) -> dict[str, Any]:
        """List references, optionally filtered by domain (GET /references)."""
        params = {"domain": domain} if domain else None
        return self._request("GET", "/references", params=params)

    def references_search(
        self,
        *,
        query: str,
        top_k: int = 5,
        domain: str | None = None,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Semantic search over reference summaries (POST /references/search)."""
        body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "include_sensitive": include_sensitive,
        }
        if domain:
            body["domain"] = domain
        return self._request("POST", "/references/search", json=body)

    def references_embed_missing(self) -> dict[str, Any]:
        """Backfill embeddings for references lacking one
        (POST /references/embed-missing)."""
        return self._request("POST", "/references/embed-missing")

    def ingest_sources(
        self,
        *,
        domain: str | None = None,
        source: str | None = None,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """List distinct ingested source_ids (GET /ingest/sources).

        Args:
            domain: Optional domain filter.
            source: Optional raw-source filter.
            include_sensitive: Reveal sources whose chunks are marked sensitive.

        Returns:
            Response dict with `sources` (each: source_id, domain, source,
            chunk_count, ingested_at) and `total`.
        """
        params: dict[str, Any] = {}
        if domain:
            params["domain"] = domain
        if source:
            params["source"] = source
        if include_sensitive:
            params["include_sensitive"] = True
        return self._request("GET", "/ingest/sources", params=params or None)

    def ingest_show(
        self,
        source_id: str,
        *,
        offset: int = 0,
        limit: int = 50,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Show one source_id's ingested chunks, paginated
        (GET /ingest/text/{source_id}).

        Args:
            source_id: Caller-supplied source id used at ingest time.
            offset: Pagination offset.
            limit: Page size.
            include_sensitive: Reveal chunks marked sensitive.

        Returns:
            Response dict with source_id, total, offset, limit, and chunks
            (each: chunk_id, text, metadata).
        """
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if include_sensitive:
            params["include_sensitive"] = True
        return self._request("GET", f"/ingest/text/{source_id}", params=params)

    def ingest_delete(self, source_id: str) -> dict[str, Any]:
        """
        Delete all ingested chunks for a source_id (un-ingest).

        Args:
            source_id: Caller-supplied source id used at ingest time.

        Returns:
            Response dict with chunks_deleted.
        """
        return self._request("DELETE", f"/ingest/text/{source_id}")

    def ingest_forget(self, source_id: str) -> dict[str, Any]:
        """
        Full forget: delete a source_id across all three ingest tiers
        (DELETE /ingest/source/{source_id}).

        Args:
            source_id: Caller-supplied source id used at ingest time.

        Returns:
            Response dict with chunks_deleted, records_deleted,
            references_deleted.
        """
        return self._request("DELETE", f"/ingest/source/{source_id}")

    # --- identity (G5): person / alias / link ---------------------------

    def entities_person(self, person: dict[str, Any]) -> dict[str, Any]:
        """Upsert a person (POST /entities/person)."""
        return self._request("POST", "/entities/person", json=person)

    def entities_alias(self, alias: dict[str, Any]) -> dict[str, Any]:
        """Bind a surface to a person (POST /entities/alias)."""
        return self._request("POST", "/entities/alias", json=alias)

    def entities_link(self, link: dict[str, Any]) -> dict[str, Any]:
        """Attach a ref to a person or record it unresolved
        (POST /entities/link)."""
        return self._request("POST", "/entities/link", json=link)

    def entities_resolve(
        self,
        *,
        surface: str,
        scope: str | None = None,
        at: str | None = None,
        ref: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Ranked candidates + evidence (GET /entities/resolve). Never picks."""
        params: dict[str, Any] = {"surface": surface}
        if scope is not None:
            params["scope"] = scope
        if at is not None:
            params["at"] = at
        if ref is not None:
            params["ref"] = ref
        if session_id is not None:
            params["session_id"] = session_id
        return self._request("GET", "/entities/resolve", params=params)

    def entities_unresolved(self) -> dict[str, Any]:
        """The unresolved-link bucket (GET /entities/unresolved)."""
        return self._request("GET", "/entities/unresolved")

    def entities_backfill(self) -> dict[str, Any]:
        """Re-score unresolved links against current aliases
        (POST /entities/backfill)."""
        return self._request("POST", "/entities/backfill")

    def estimate_index(
        self,
        folder_path: str,
        recursive: bool = True,
        include_code: bool = False,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        include_types: list[str] | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> dict[str, Any]:
        """Approximate embedding-token cost of indexing a folder (no enqueue).

        Mirrors the file-selection arguments of ``index`` so the estimate
        reflects exactly what would be indexed. Returns the server's estimate
        dict (files, est_embedding_tokens, tokenizer, …).
        """
        body: dict[str, Any] = {
            "folder_path": folder_path,
            "recursive": recursive,
            "include_code": include_code,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }
        if include_types is not None:
            body["include_types"] = include_types
        return self._request("POST", "/index/estimate", json=body)

    def list_folders(self) -> list[FolderInfo]:
        """
        List all indexed folders.

        Returns:
            List of FolderInfo objects sorted by folder path.
        """
        data = self._request("GET", "/index/folders/")
        folders: list[FolderInfo] = [
            FolderInfo(
                folder_path=f["folder_path"],
                chunk_count=f["chunk_count"],
                last_indexed=f["last_indexed"],
                watch_mode=f.get("watch_mode", "off"),
                watch_debounce_seconds=f.get("watch_debounce_seconds"),
            )
            for f in data.get("folders", [])
        ]
        return folders

    def delete_folder(self, folder_path: str) -> dict[str, Any]:
        """
        Delete all indexed chunks for a folder.

        Args:
            folder_path: Absolute path to the folder to remove.

        Returns:
            Response dict with folder_path, chunks_deleted, and message.
        """
        result: dict[str, Any] = self._request(
            "DELETE",
            "/index/folders/",
            json={"folder_path": folder_path},
        )
        return result

    def reset(self) -> IndexResponse:
        """
        Reset the index by deleting all documents.

        Returns:
            IndexResponse confirming reset.
        """
        data = self._request("DELETE", "/index/")

        return IndexResponse(
            job_id=data.get("job_id", "reset"),
            status=data["status"],
            message=data.get("message"),
        )

    def list_jobs_page(
        self, limit: int = 20, offset: int = 0, all_: bool = False
    ) -> dict[str, Any]:
        """
        Full jobs-list payload: jobs + queue counts + the no-op-hidden hint.

        Args:
            limit: Maximum number of jobs to return.
            offset: Number of jobs to skip.
            all_: Reveal no-op completed jobs (status=done, no chunk delta,
                no error) that are hidden by default (Fix 4).

        Returns:
            The raw JobListResponse dict (jobs/total/.../noop_hidden).
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if all_:
            params["all"] = 1
        return self._request("GET", "/index/jobs/", params=params)

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        List jobs in the queue (back-compat: jobs list only, no-op hidden by
        default). Prefer ``list_jobs_page`` when you also need counts/hints.

        Args:
            limit: Maximum number of jobs to return.

        Returns:
            List of job dictionaries.
        """
        data = self.list_jobs_page(limit=limit)
        jobs: list[dict[str, Any]] = data.get("jobs", [])
        return jobs

    def get_job(self, job_id: str) -> dict[str, Any]:
        """
        Get details for a specific job.

        Args:
            job_id: The job ID to look up.

        Returns:
            Job detail dictionary.
        """
        return self._request("GET", f"/index/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """
        Cancel a specific job.

        Args:
            job_id: The job ID to cancel.

        Returns:
            Cancellation result dictionary.
        """
        return self._request("DELETE", f"/index/jobs/{job_id}")

    def approve_job(self, job_id: str) -> dict[str, Any]:
        """
        Approve a budget-blocked job (re-queues it with force_budget).

        Args:
            job_id: The blocked job ID to approve.

        Returns:
            Approval result dictionary ({"job_id", "status", "message"}).
        """
        return self._request("POST", f"/index/jobs/{job_id}/approve")

    def cache_status(self) -> dict[str, Any]:
        """
        Get embedding cache status.

        Returns:
            Dict with hits, misses, hit_rate, mem_entries, entry_count, size_bytes.

        Raises:
            ConnectionError: If unable to connect.
            ServerError: If server returns an error.
        """
        return self._request("GET", "/index/cache/")

    def clear_cache(self) -> dict[str, Any]:
        """
        Clear the embedding cache.

        Returns:
            Dict with count, size_bytes, size_mb of cleared entries.

        Raises:
            ConnectionError: If unable to connect.
            ServerError: If server returns an error.
        """
        return self._request("DELETE", "/index/cache/")

    def graph_path(
        self,
        src: str,
        dst: str,
        max_depth: int = 6,
        limit: int = 5,
        domains: str | None = None,
    ) -> dict[str, Any]:
        """Shortest paths between two graph nodes (GET /graph/path)."""
        params: dict[str, Any] = {
            "src": src,
            "dst": dst,
            "max_depth": max_depth,
            "limit": limit,
        }
        if domains:
            params["domains"] = domains
        return self._request("GET", "/graph/path", params=params)

    def graph_impact(
        self,
        node: str,
        max_depth: int = 3,
        predicates: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Reverse dependency closure for a node (GET /graph/impact)."""
        params: dict[str, Any] = {
            "node": node,
            "max_depth": max_depth,
            "limit": limit,
        }
        if predicates:
            params["predicates"] = predicates
        return self._request("GET", "/graph/impact", params=params)

    def graph_cochange(
        self, node: str, min_shared: int = 2, limit: int = 20
    ) -> dict[str, Any]:
        """Git co-change files for a file node (GET /graph/cochange)."""
        return self._request(
            "GET",
            "/graph/cochange",
            params={"node": node, "min_shared": min_shared, "limit": limit},
        )

    # ----- Curated memory namespace (Phase 030) -------------------------

    def remember(
        self,
        text: str,
        section: str = "Notes",
        tags: list[str] | None = None,
        origin: str = "user",
    ) -> dict[str, Any]:
        """Create a curated memory."""
        return self._request(
            "POST",
            "/memories/",
            json={
                "text": text,
                "section": section,
                "tags": tags or [],
                "origin": origin,
            },
        )

    def recall(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """Recall from the memory namespace only."""
        return self._request(
            "POST", "/memories/recall", json={"query": query, "top_k": top_k}
        )

    def list_memories(
        self,
        tag: str | None = None,
        section: str | None = None,
        include_obsolete: bool = False,
    ) -> dict[str, Any]:
        """List curated memories."""
        params: dict[str, Any] = {"include_obsolete": include_obsolete}
        if tag:
            params["tag"] = tag
        if section:
            params["section"] = section
        return self._request("GET", "/memories/", params=params)

    def delete_memory(self, memory_id: str) -> dict[str, Any]:
        """Delete a curated memory by id."""
        return self._request("DELETE", f"/memories/{memory_id}")

    def obsolete_memory(
        self, memory_id: str, superseded_by: str | None = None
    ) -> dict[str, Any]:
        """Mark a curated memory obsolete."""
        params = {"superseded_by": superseded_by} if superseded_by else None
        return self._request("POST", f"/memories/{memory_id}/obsolete", params=params)

    # ----- Session-start context (Phase 035) ---------------------------

    def session_context(self) -> dict[str, Any]:
        """Fetch the session-start context block."""
        return self._request("GET", "/context/session-start")

    def submit_session_extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a session extraction payload (Phase 060)."""
        return self._request("POST", "/sessions/extract", json=payload)

    def submit_session_distill(
        self, paths: list[str], force: bool = False
    ) -> dict[str, Any]:
        """Enqueue provider-engine distillation of transcripts (Phase 080)."""
        return self._request(
            "POST", "/sessions/distill", json={"paths": paths, "force": force}
        )

    # ----- Graph-extraction drain queue (Plan 3) ------------------------

    def get_extraction_pending(self, limit: int, source: str = "all") -> dict[str, Any]:
        """Fetch a bounded batch of pending extraction items (Plan 3).

        ``source`` filters the queue server-side: ``doc`` (skips the session
        archive scan — findings 3-5/3-6), ``session``, or ``all`` (default).
        """
        return self._request(
            "GET", f"/extraction/pending?limit={limit}&source={source}"
        )

    def get_extraction_text(self, chunk_id: str) -> dict[str, Any]:
        """Fetch one pending chunk's text by id (404 when not pending)."""
        return self._request("GET", f"/extraction/text/{chunk_id}")

    def submit_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit an extraction payload (doc triplets or session extraction)."""
        return self._request("POST", "/extraction/submit", json=payload)

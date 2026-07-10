"""Graph index manager for GraphRAG (Feature 113).

Manages graph index building and querying for the knowledge graph.
Coordinates between extractors, graph store, and vector store.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from brainpalace_server.config import settings
from brainpalace_server.indexing.graph_extractors import (
    CodeMetadataExtractor,
    LLMEntityExtractor,
    get_code_extractor,
    get_llm_extractor,
)
from brainpalace_server.models.graph import (
    GraphIndexStatus,
    GraphQueryContext,
    GraphTriple,
    normalize_entity_type,
)
from brainpalace_server.storage.graph_store import (
    GraphStoreManager,
    get_graph_store_manager,
)

logger = logging.getLogger(__name__)


# Type for progress callbacks
ProgressCallback = Callable[[int, int, str], None]


class GraphIndexManager:
    """Manages graph index building and querying.

    Coordinates:
    - Entity extraction from documents (LLM and code metadata)
    - Triplet storage in GraphStoreManager
    - Graph-based retrieval for queries

    Extraction routing:
    - source_type == "code"     → CodeMetadataExtractor (AST, no API key)
    - source_type == "document" → deferred via DocPendingStore to async reconciler

    All operations are no-ops when ENABLE_GRAPH_INDEX is False.

    Attributes:
        graph_store: The underlying graph store manager.
        llm_extractor: LLM-based entity extractor (retained for direct API use).
        code_extractor: Code metadata extractor.
        pending_store: Optional per-chunk pending queue (deferred doc extraction).
    """

    def __init__(
        self,
        graph_store: GraphStoreManager | None = None,
        llm_extractor: LLMEntityExtractor | None = None,
        code_extractor: CodeMetadataExtractor | None = None,
        pending_store: Any | None = None,
    ) -> None:
        """Initialize graph index manager.

        Args:
            graph_store: Graph store manager (defaults to singleton).
            llm_extractor: LLM extractor (defaults to singleton).
            code_extractor: Code extractor (defaults to singleton).
            pending_store: Optional per-chunk pending queue (deferred doc extraction).
        """
        self.graph_store = graph_store or get_graph_store_manager()
        self.llm_extractor = llm_extractor or get_llm_extractor()
        self.code_extractor = code_extractor or get_code_extractor()
        self.pending_store = pending_store
        self._last_build_time: datetime | None = None
        self._last_triplet_count: int = 0
        self._lsp_extractor: Any | None = None  # lazy (Phase 150, opt-in)

    def _get_lsp_extractor(self, root: str | None = None) -> Any:
        """Lazily build the opt-in LSP cross-ref extractor (Phase 150).

        The first call fixes the workspace root (stable per project) — real
        language servers need it to index the workspace."""
        if self._lsp_extractor is None:
            from brainpalace_server.lsp.extractor import LspCrossRefExtractor

            root_uri = f"file://{root}" if root else ""
            self._lsp_extractor = LspCrossRefExtractor(root_uri=root_uri)
        return self._lsp_extractor

    def build_from_documents(
        self,
        documents: list[Any],
        progress_callback: ProgressCallback | None = None,
        root: str | None = None,
    ) -> int:
        """Build graph index from documents.

        Extracts entities and relationships from document chunks
        and stores them in the graph.

        Args:
            documents: List of document chunks with text and metadata.
            progress_callback: Optional callback(current, total, message).
            root: Indexed folder root — enables the Folder chain and bounds
                import resolution.

        Returns:
            Total number of triplets extracted and stored.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            logger.debug(
                "graph_index.build_from_documents: skipped (ENABLE_GRAPH_INDEX=false)"
            )
            return 0

        # Ensure graph store is initialized
        if not self.graph_store.is_initialized:
            logger.info("graph_index.build_from_documents: initializing graph store")
            self.graph_store.initialize()

        total_triplets = 0

        from collections import defaultdict

        from brainpalace_server.indexing.code_symbol_extractor import (
            extract_python_symbols,
        )
        from brainpalace_server.indexing.import_resolver import resolve_import
        from brainpalace_server.indexing.manifest_deps import (
            extract_manifest_deps,
            is_manifest,
        )
        from brainpalace_server.lsp import servers

        py_by_file: dict[str, list[Any]] = defaultdict(list)
        manifest_by_file: dict[str, list[Any]] = defaultdict(list)
        rest: list[Any] = []
        for doc in documents:
            md = self._get_document_metadata(doc)
            fp = md.get("file_path") or md.get("source")
            if fp and is_manifest(fp):
                manifest_by_file[fp.replace("\\", "/")].append(doc)
            elif (
                md.get("source_type") == "code"
                and md.get("language") == "python"
                and fp
            ):
                py_by_file[fp.replace("\\", "/")].append(doc)
            else:
                rest.append(doc)

        def _doc_text(d: Any) -> str:
            if isinstance(d, dict):  # dict-shaped chunk: text lives under a key
                return d.get("text", "") or ""
            return getattr(d, "text", "") or (
                d.get_content() if hasattr(d, "get_content") else ""
            )

        def _write(
            tr: GraphTriple,
            source_file: str | None,
            source_chunk_id: str | None = None,
        ) -> bool:
            return bool(
                self.graph_store.add_triplet(
                    subject=tr.subject,
                    predicate=tr.predicate,
                    obj=tr.object,
                    subject_type=tr.subject_type,
                    object_type=tr.object_type,
                    source_chunk_id=source_chunk_id,
                    subject_id=tr.effective_subject_id,
                    object_id=tr.effective_object_id,
                    subject_name=tr.subject_name,
                    object_name=tr.object_name,
                    source_file=source_file,
                    domain="code",
                )
            )

        for fp, docs in py_by_file.items():
            self.graph_store.invalidate_by_source_file(fp, domain="code")
            rep_chunk = self._get_document_id(docs[0])
            source = "\n".join(_doc_text(d) for d in docs)
            try:
                file_symbols = extract_python_symbols(fp, source, root=root)
            except Exception:  # noqa: BLE001 — one bad file must not kill the build
                logger.warning(
                    "code symbol extraction failed for %s; skipping file",
                    fp,
                    exc_info=True,
                )
                continue
            for tr in file_symbols.triples:
                # Folder→Folder chain edges carry source_file=None on purpose
                # (shared across files; removed by sweep_empty_folders).
                if _write(tr, tr.source_file, rep_chunk):
                    total_triplets += 1

            # Plan D: persist definition positions onto the symbol nodes so the
            # browser can show file:line and serve source snippets. Merge-write
            # after the triple writes (nodes must exist); the preserve-on-empty
            # upsert keeps these across later edge writes from other files.
            if file_symbols.symbols:
                self.graph_store.set_node_properties(
                    {
                        s.symbol_id: {
                            "path": s.file_path.replace("\\", "/"),
                            "line": s.line,
                            "character": s.character,
                        }
                        for s in file_symbols.symbols
                        if s.symbol_id
                    }
                )

            # §2b import resolution: repo hit → File imports File; miss on an
            # absolute import → external Module; miss on a relative one → nothing.
            fname = fp.rsplit("/", 1)[-1]
            for spec in file_symbols.imports:
                targets = resolve_import(
                    fp, spec.module, spec.level, spec.names, root=root
                )
                if targets:
                    for target in targets:
                        tname = target.rsplit("/", 1)[-1]
                        if _write(
                            GraphTriple(
                                subject=fname,
                                predicate="imports",
                                object=tname,
                                subject_id=fp,
                                object_id=target,
                                subject_name=fname,
                                object_name=tname,
                                subject_type="File",
                                object_type="File",
                                source_file=fp,
                            ),
                            fp,
                            rep_chunk,
                        ):
                            total_triplets += 1
                elif spec.level == 0 and spec.module:
                    if _write(
                        GraphTriple(
                            subject=fname,
                            predicate="imports",
                            object=spec.module,
                            subject_id=fp,
                            object_id=spec.module,
                            subject_name=fname,
                            object_name=spec.module,
                            subject_type="File",
                            object_type="Module",
                            source_file=fp,
                        ),
                        fp,
                        rep_chunk,
                    ):
                        total_triplets += 1

            # LSP precision (§4/§5b): exact cross-file calls + references, fed
            # the AST tables. Gated + fail-soft; forced source_file so the §3
            # purge owns every LSP triplet.
            if servers.is_language_enabled("python"):
                if file_symbols.symbols:
                    for tr in self._get_lsp_extractor(root).extract_from_symbols(
                        file_symbols.symbols
                    ):
                        if _write(tr, fp, rep_chunk):
                            total_triplets += 1
                if file_symbols.ref_sites:
                    for tr in self._get_lsp_extractor(root).extract_references(
                        file_symbols.ref_sites
                    ):
                        if _write(tr, fp, rep_chunk):
                            total_triplets += 1

            self.graph_store.sweep_orphan_nodes(domain="code")

        # §5b depends_on: manifests are deterministic; same purge→write cycle.
        for fp, docs in manifest_by_file.items():
            self.graph_store.invalidate_by_source_file(fp, domain="code")
            rep_chunk = self._get_document_id(docs[0])
            source = "\n".join(_doc_text(d) for d in docs)
            for tr in extract_manifest_deps(fp, source):
                if _write(tr, fp, rep_chunk):
                    total_triplets += 1
            self.graph_store.sweep_orphan_nodes(domain="code")

        if py_by_file or manifest_by_file:
            self.graph_store.sweep_empty_folders(domain="code")

        if self._lsp_extractor is not None:
            # Tear down spawned language servers; the extractor stays cached
            # and respawns clients lazily on the next build.
            self._lsp_extractor.close()

        documents = rest
        total_docs = len(documents)

        logger.info(
            "graph_index.build_from_documents: starting",
            extra={
                "document_count": total_docs,
                "code_metadata": settings.GRAPH_USE_CODE_METADATA,
            },
        )

        for idx, doc in enumerate(documents):
            if progress_callback:
                progress_callback(
                    idx + 1,
                    total_docs,
                    f"Extracting entities: {idx + 1}/{total_docs}",
                )

            triplets = self._extract_from_document(doc)

            for triplet in triplets:
                success = self.graph_store.add_triplet(
                    subject=triplet.subject,
                    predicate=triplet.predicate,
                    obj=triplet.object,
                    subject_type=triplet.subject_type,
                    object_type=triplet.object_type,
                    source_chunk_id=triplet.source_chunk_id,
                )
                if success:
                    total_triplets += 1

        # Persist the graph
        self.graph_store.persist()
        self._last_build_time = datetime.now(timezone.utc)
        self._last_triplet_count = total_triplets

        logger.info(
            "graph_index.build_from_documents: completed",
            extra={
                "triplet_count": total_triplets,
                "document_count": total_docs,
                "entity_count": self.graph_store.entity_count,
                "relationship_count": self.graph_store.relationship_count,
            },
        )

        # Record code-AST triplets — best-effort; never breaks the caller (§6-F5).
        if total_triplets > 0:
            try:
                from brainpalace_server.services.usage_metrics import (  # noqa: PLC0415
                    record_usage,
                )

                record_usage("code-ast", "", "", "code", triplets=total_triplets)
            except Exception:  # noqa: BLE001
                pass

        return total_triplets

    def _extract_from_document(self, doc: Any) -> list[GraphTriple]:
        """Extract triplets from a single document.

        Uses both code metadata extractor and LLM extractor
        depending on document type and settings.

        Args:
            doc: Document with text content and metadata.

        Returns:
            List of GraphTriple objects.
        """
        triplets: list[GraphTriple] = []

        # Get document properties
        text = self._get_document_text(doc)
        metadata = self._get_document_metadata(doc)
        chunk_id = self._get_document_id(doc)
        source_type = metadata.get("source_type", "doc")
        language = metadata.get("language")

        # 1. Extract from code metadata (fast, deterministic — code chunks only)
        if source_type == "code" and settings.GRAPH_USE_CODE_METADATA:
            code_triplets = self.code_extractor.extract_from_metadata(
                metadata, source_chunk_id=chunk_id
            )
            triplets.extend(code_triplets)

            # Also try pattern-based extraction from text. Pass the importing
            # file's real module name so import edges are attributed to it
            # (not one shared "current_module" hub), which is what makes a
            # node's callers — and the chain up to the entry point — visible.
            if language:
                file_path = metadata.get("file_path") or metadata.get("source")
                module_name = (
                    self.code_extractor._extract_module_name(file_path)
                    if file_path
                    else None
                )
                text_triplets = self.code_extractor.extract_from_text(
                    text,
                    language=language,
                    source_chunk_id=chunk_id,
                    module_name=module_name,
                )
                triplets.extend(text_triplets)

            # LSP cross-references (Phase 150) — opt-in + fail-soft. Inert
            # unless BRAINPALACE_LSP_LANGUAGES lists a language, so the default
            # indexing path is unchanged.
            from brainpalace_server.lsp import servers

            if servers.enabled_languages():
                lsp_triplets = self._get_lsp_extractor().extract_from_metadata(
                    metadata, source_chunk_id=chunk_id
                )
                triplets.extend(lsp_triplets)

        # 2. Document chunks — DEFER to the async reconciler via the pending store
        #    (spec §8 — no synchronous LLM burst at index time). When no store is
        #    wired the chunk is silently skipped; code-AST extraction is unaffected.
        if text and source_type != "code":
            if self.pending_store is not None:
                # Split git-commit chunks out from doc-file chunks so the queue
                # backlog widget can report them separately (same pending table).
                kind = "git" if source_type == "git_commit" else "doc"
                self.pending_store.mark_pending(chunk_id, text, kind=kind)

        return triplets

    def _get_document_text(self, doc: Any) -> str:
        """Get text content from document."""
        if hasattr(doc, "text"):
            return str(doc.text)
        elif hasattr(doc, "get_content"):
            return str(doc.get_content())
        elif hasattr(doc, "page_content"):
            return str(doc.page_content)
        elif isinstance(doc, dict):
            text = doc.get("text", doc.get("content", ""))
            return str(text) if text else ""
        return str(doc)

    def _get_document_metadata(self, doc: Any) -> dict[str, Any]:
        """Get metadata from document."""
        if hasattr(doc, "metadata"):
            meta = doc.metadata
            if hasattr(meta, "to_dict"):
                result = meta.to_dict()
                return dict(result) if result else {}
            elif isinstance(meta, dict):
                return dict(meta)
        elif isinstance(doc, dict):
            meta = doc.get("metadata", {})
            return dict(meta) if meta else {}
        return {}

    def _get_document_id(self, doc: Any) -> str | None:
        """Get document/chunk ID."""
        if hasattr(doc, "chunk_id"):
            val = doc.chunk_id
            return str(val) if val else None
        elif hasattr(doc, "id_"):
            val = doc.id_
            return str(val) if val else None
        elif hasattr(doc, "node_id"):
            val = doc.node_id
            return str(val) if val else None
        elif isinstance(doc, dict):
            val = doc.get("chunk_id", doc.get("id"))
            return str(val) if val else None
        return None

    def query(
        self,
        query_text: str,
        top_k: int = 10,
        traversal_depth: int = 2,
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Query the graph for related entities and documents.

        Performs entity recognition on query, finds matching nodes,
        and traverses relationships to discover related content.

        Args:
            query_text: Natural language query.
            top_k: Maximum number of results to return.
            traversal_depth: How many hops to traverse in graph.

        Returns:
            List of result dicts with entity info and relationship paths.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            logger.debug(
                "graph_index.query: skipped (ENABLE_GRAPH_INDEX=false)",
                extra={"query": query_text[:100]},
            )
            return []

        if not self.graph_store.is_initialized:
            logger.debug(
                "graph_index.query: skipped (store not initialized)",
                extra={"query": query_text[:100]},
            )
            return []

        # Get graph store for querying
        graph_store = self.graph_store.graph_store
        if graph_store is None:
            logger.debug(
                "graph_index.query: skipped (no graph store)",
                extra={"query": query_text[:100]},
            )
            return []

        results: list[dict[str, Any]] = []

        # Extract potential entity names from query
        query_entities = self._extract_query_entities(query_text)

        logger.debug(
            "graph_index.query: extracted entities",
            extra={
                "query": query_text[:100],
                "entity_count": len(query_entities),
                "entities": query_entities[:5],
            },
        )

        # Find matching entities and their relationships
        for entity in query_entities:
            entity_results = self._find_entity_relationships(
                entity, traversal_depth, top_k, include_sensitive=include_sensitive
            )
            results.extend(entity_results)

        # Deduplicate and sort by relevance
        seen_keys: set[str] = set()
        unique_results: list[dict[str, Any]] = []
        for result in results:
            # Use source_chunk_id if available, otherwise use relationship path
            chunk_id = result.get("source_chunk_id")
            rel_path = result.get("relationship_path", "")
            dedup_key = chunk_id if chunk_id else rel_path

            if dedup_key and dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                unique_results.append(result)
            elif not dedup_key:
                # No dedup key available, still include result
                unique_results.append(result)

        # Weight-aware ordering: higher-confidence edges first (deterministic
        # edges carry no weight ⇒ 1.0). Stable sort keeps discovery order
        # between equals; this rank order is what multi-mode RRF consumes.
        unique_results.sort(key=lambda r: r.get("graph_score", 1.0), reverse=True)
        final_results = unique_results[:top_k]

        logger.info(
            "graph_index.query: completed",
            extra={
                "query": query_text[:100],
                "result_count": len(final_results),
                "entities_searched": len(query_entities),
                "top_k": top_k,
                "traversal_depth": traversal_depth,
            },
        )

        return final_results

    def query_by_type(
        self,
        query_text: str,
        entity_types: list[str] | None = None,
        relationship_types: list[str] | None = None,
        top_k: int = 10,
        traversal_depth: int = 2,
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Query graph filtered by entity and/or relationship types.

        Fetches extra results from the base query, then filters by
        entity types and relationship types before returning top_k.

        Args:
            query_text: Natural language query.
            entity_types: Filter to results involving these entity types
                (matches against subject_type or object_type).
            relationship_types: Filter to results with these predicates.
            top_k: Maximum results to return after filtering.
            traversal_depth: Graph traversal depth.

        Returns:
            Filtered list of result dicts.
        """
        # No filters: delegate directly to base query (no overhead)
        if not entity_types and not relationship_types:
            return self.query(
                query_text,
                top_k=top_k,
                traversal_depth=traversal_depth,
                include_sensitive=include_sensitive,
            )

        # Over-fetch to ensure enough results after filtering
        fetch_k = top_k * 3
        candidate_results = self.query(
            query_text,
            top_k=fetch_k,
            traversal_depth=traversal_depth,
            include_sensitive=include_sensitive,
        )

        if not candidate_results:
            return []

        # Normalize filter types for case-insensitive comparison
        normalized_entity_types: set[str | None] = set()
        if entity_types:
            for et in entity_types:
                normalized = normalize_entity_type(et)
                if normalized:
                    normalized_entity_types.add(normalized)

        normalized_relationship_types: set[str] = set()
        if relationship_types:
            normalized_relationship_types = {rt.lower() for rt in relationship_types}

        # Filter results
        filtered_results: list[dict[str, Any]] = []
        for result in candidate_results:
            # Filter by entity_types
            if entity_types:
                subject_type = result.get("subject_type")
                object_type = result.get("object_type")
                # Normalize the result types
                norm_subject = normalize_entity_type(subject_type)
                norm_object = normalize_entity_type(object_type)
                # Match if either subject_type or object_type is in filter
                if (
                    norm_subject not in normalized_entity_types
                    and norm_object not in normalized_entity_types
                ):
                    continue

            # Filter by relationship_types
            if relationship_types:
                predicate = result.get("predicate", "").lower()
                if predicate not in normalized_relationship_types:
                    continue

            filtered_results.append(result)

        # Limit to top_k
        final_results = filtered_results[:top_k]

        logger.info(
            "graph_index.query_by_type: completed",
            extra={
                "query": query_text[:100],
                "candidates": len(candidate_results),
                "filtered": len(filtered_results),
                "returned": len(final_results),
                "entity_types": entity_types,
                "relationship_types": relationship_types,
            },
        )

        return final_results

    def _extract_query_entities(self, query_text: str) -> list[str]:
        """Extract potential entity names from query text.

        Uses simple heuristics to identify entity-like terms.

        Args:
            query_text: Query text to analyze.

        Returns:
            List of potential entity names.
        """
        import re

        entities: list[str] = []

        # Split into words
        words = query_text.split()

        # Look for CamelCase or PascalCase words
        for word in words:
            # Remove punctuation
            clean_word = re.sub(r"[^\w]", "", word)
            if not clean_word:
                continue

            # CamelCase detection
            if re.match(r"^[A-Z][a-z]+[A-Z]", clean_word):
                entities.append(clean_word)
            # ALL_CAPS constants
            elif re.match(r"^[A-Z_]+$", clean_word) and len(clean_word) > 2:
                entities.append(clean_word)
            # Capitalized words (potential class names)
            elif clean_word[0].isupper() and len(clean_word) > 2:
                entities.append(clean_word)
            # snake_case function names
            elif "_" in clean_word and clean_word.islower():
                entities.append(clean_word)

        # Also include significant lowercase terms
        for word in words:
            clean_word = re.sub(r"[^\w]", "", word).lower()
            if len(clean_word) > 3 and clean_word not in (
                "what",
                "where",
                "when",
                "which",
                "that",
                "this",
                "have",
                "does",
                "with",
                "from",
                "about",
                "into",
            ):
                if clean_word not in [e.lower() for e in entities]:
                    entities.append(clean_word)

        return entities[:10]  # Limit to prevent query explosion

    def _find_entity_relationships(
        self,
        entity: str,
        depth: int,
        max_results: int,
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Find entity relationships in the graph.

        Args:
            entity: Entity name to search for.
            depth: Traversal depth.
            max_results: Maximum results per entity.

        Returns:
            List of result dictionaries.
        """
        results: list[dict[str, Any]] = []
        graph_store = self.graph_store.graph_store

        if graph_store is None:
            return results

        # Try to get triplets from graph store
        try:
            entity_lower = entity.lower()
            if hasattr(graph_store, "search_nodes"):
                # SQLite backend: push the substring match into SQL (indexed,
                # degree-ranked) instead of scanning every node in Python.
                matched_names = list(
                    {
                        m["name"]
                        for m in graph_store.search_nodes(
                            entity, limit=25, include_sensitive=include_sensitive
                        )
                    }
                )
                if not matched_names:
                    return results
                triplets = graph_store.get_triplets(
                    entity_names=matched_names, include_sensitive=include_sensitive
                )
            elif hasattr(graph_store, "get_triplets") and hasattr(graph_store, "get"):
                # Property-graph store without browse reads (simple backend).
                all_nodes = graph_store.get()
                matched_names = []
                for node in all_nodes:
                    name = getattr(node, "name", None)
                    if name is None:
                        continue
                    if entity_lower == name.lower() or entity_lower in name.lower():
                        matched_names.append(name)
                if not matched_names:
                    return results
                triplets = graph_store.get_triplets(entity_names=matched_names)
            elif hasattr(graph_store, "_relationships"):
                triplets = graph_store._relationships
            else:
                return results

            # Filter triplets to those whose subject OR object contains entity.
            # Weight is computed here (not deferred to the build loop) so the
            # per-entity truncation below can sort by it — otherwise a
            # high-weight edge discovered late is dropped in favor of an
            # earlier weight-1.0 edge, silently defeating the weight sort.
            matching_triplets: list[tuple[float, Any]] = []
            seen: set[tuple[str, str, str]] = set()
            for triplet in triplets:
                subject = self._get_triplet_field(triplet, "subject", "")
                obj = self._get_triplet_field(triplet, "object", "")
                predicate = self._get_triplet_field(triplet, "predicate", "")
                if entity_lower in subject.lower() or entity_lower in obj.lower():
                    key = (subject, predicate, obj)
                    if key in seen:
                        continue
                    seen.add(key)
                    weight = float(self._get_triplet_field(triplet, "weight", 1.0))
                    matching_triplets.append((weight, triplet))

            # Weight-aware per-entity cut: highest-weight edges survive the
            # truncation (stable sort keeps discovery order among ties).
            matching_triplets.sort(key=lambda pair: pair[0], reverse=True)

            # Build result entries from matching triplets
            for weight, triplet in matching_triplets[:max_results]:
                result = {
                    "entity": entity,
                    "subject": self._get_triplet_field(triplet, "subject", ""),
                    "subject_type": self._get_triplet_field(
                        triplet, "subject_type", None
                    ),
                    "predicate": self._get_triplet_field(triplet, "predicate", ""),
                    "object": self._get_triplet_field(triplet, "object", ""),
                    "object_type": self._get_triplet_field(
                        triplet, "object_type", None
                    ),
                    "source_chunk_id": self._get_triplet_field(
                        triplet, "source_chunk_id", None
                    ),
                    "relationship_path": self._format_relationship_path(triplet),
                    "graph_score": weight,
                }
                results.append(result)

        except Exception as e:
            logger.warning(f"Error querying graph store: {e}")

        return results

    def _get_triplet_field(self, triplet: Any, field: str, default: Any) -> Any:
        """Get field from triplet.

        Handles three shapes:
        - dict-style: {"subject": ..., "predicate": ..., ...}
        - object-style: attributes named subject/predicate/object/...
        - property-graph tuple: (EntityNode, Relation, EntityNode) where
          subject = triplet[0].name, predicate = triplet[1].label, etc.
        """
        if isinstance(triplet, dict):
            return triplet.get(field, default)
        if isinstance(triplet, (tuple, list)) and len(triplet) == 3:
            subj, rel, obj = triplet
            if field == "subject":
                return getattr(subj, "name", default)
            if field == "subject_type":
                return getattr(subj, "label", default)
            if field == "predicate":
                return getattr(rel, "label", default)
            if field == "object":
                return getattr(obj, "name", default)
            if field == "object_type":
                return getattr(obj, "label", default)
            if field == "source_chunk_id":
                props = getattr(rel, "properties", None) or {}
                return props.get("source_chunk_id", default)
            if field == "weight":
                props = getattr(rel, "properties", None) or {}
                try:
                    return float(props.get("weight", default))
                except (TypeError, ValueError):
                    return default
            return default
        return getattr(triplet, field, default)

    def _format_relationship_path(self, triplet: Any) -> str:
        """Format a triplet as a relationship path string."""
        subject = self._get_triplet_field(triplet, "subject", "?")
        predicate = self._get_triplet_field(triplet, "predicate", "?")
        obj = self._get_triplet_field(triplet, "object", "?")
        return f"{subject} -> {predicate} -> {obj}"

    def get_graph_context(
        self,
        query_text: str,
        top_k: int = 5,
        traversal_depth: int = 2,
    ) -> GraphQueryContext:
        """Get graph context for a query.

        Returns structured context information from the knowledge graph
        that can be used to augment retrieval results.

        Args:
            query_text: Natural language query.
            top_k: Maximum entities to include.
            traversal_depth: Graph traversal depth.

        Returns:
            GraphQueryContext with related entities and paths.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            return GraphQueryContext()

        results = self.query(query_text, top_k=top_k, traversal_depth=traversal_depth)

        if not results:
            return GraphQueryContext()

        # Extract unique entities
        related_entities: list[str] = []
        relationship_paths: list[str] = []
        subgraph_triplets: list[GraphTriple] = []

        seen_entities: set[str] = set()
        for result in results:
            # Add entities
            for entity_field in ["subject", "object"]:
                entity = result.get(entity_field)
                if entity and entity not in seen_entities:
                    seen_entities.add(entity)
                    related_entities.append(entity)

            # Add relationship path
            path = result.get("relationship_path")
            if path and path not in relationship_paths:
                relationship_paths.append(path)

            # Create triplet
            try:
                triplet = GraphTriple(
                    subject=result.get("subject", ""),
                    predicate=result.get("predicate", ""),
                    object=result.get("object", ""),
                    source_chunk_id=result.get("source_chunk_id"),
                )
                subgraph_triplets.append(triplet)
            except Exception:
                pass

        # Calculate average graph score
        scores = [r.get("graph_score", 0.0) for r in results if r.get("graph_score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        return GraphQueryContext(
            related_entities=related_entities[:top_k],
            relationship_paths=relationship_paths[:top_k],
            subgraph_triplets=subgraph_triplets[:top_k],
            graph_score=min(avg_score, 1.0),
        )

    def get_status(self) -> GraphIndexStatus:
        """Get current graph index status.

        Returns:
            GraphIndexStatus with entity/relationship counts.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            return GraphIndexStatus(
                enabled=False,
                initialized=False,
                entity_count=0,
                relationship_count=0,
                store_type=settings.GRAPH_STORE_TYPE,
            )

        return GraphIndexStatus(
            enabled=True,
            initialized=self.graph_store.is_initialized,
            entity_count=self.graph_store.entity_count,
            relationship_count=self.graph_store.relationship_count,
            last_updated=self.graph_store.last_updated,
            store_type=self.graph_store.store_type,
        )

    def clear(self) -> None:
        """Clear the graph index."""
        if settings.ENABLE_GRAPH_INDEX and self.graph_store.is_initialized:
            prev_triplet_count = self._last_triplet_count
            self.graph_store.clear()
            self._last_build_time = None
            self._last_triplet_count = 0
            logger.info(
                "graph_index.clear: completed",
                extra={"previous_triplet_count": prev_triplet_count},
            )
        else:
            logger.debug(
                "graph_index.clear: skipped",
                extra={
                    "enabled": settings.ENABLE_GRAPH_INDEX,
                    "initialized": (
                        self.graph_store.is_initialized
                        if settings.ENABLE_GRAPH_INDEX
                        else False
                    ),
                },
            )


# Module-level singleton
_graph_index_manager: GraphIndexManager | None = None


def get_graph_index_manager() -> GraphIndexManager:
    """Get the global graph index manager instance."""
    global _graph_index_manager
    if _graph_index_manager is None:
        _graph_index_manager = GraphIndexManager()
    return _graph_index_manager


def reset_graph_index_manager() -> None:
    """Reset the global graph index manager. Used for testing."""
    global _graph_index_manager
    _graph_index_manager = None

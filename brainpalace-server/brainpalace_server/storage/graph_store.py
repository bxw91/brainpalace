"""Graph store manager for GraphRAG feature (Feature 113).

Graph storage backends:
- SimplePropertyGraphStore: in-memory graph with JSON persistence.
- SQLitePropertyGraphStore: persistent, incremental, temporal (sqlite3).

The active backend is selected by ``store_type``; an unknown value downgrades
to ``simple`` with a warning. All graph operations are no-ops when
ENABLE_GRAPH_INDEX is False.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from brainpalace_server.config import settings

logger = logging.getLogger(__name__)


class GraphStoreManager:
    """Manages graph storage for GraphRAG.

    Uses SimplePropertyGraphStore (the only supported backend).
    Implements singleton pattern for consistent graph access.

    Attributes:
        persist_dir: Directory for graph persistence.
        store_type: Backend type - always "simple".
    """

    _instance: Optional["GraphStoreManager"] = None

    def __init__(self, persist_dir: Path, store_type: str = "simple") -> None:
        """Initialize graph store manager.

        Args:
            persist_dir: Directory for graph persistence.
            store_type: Backend type - only "simple" is supported.
        """
        self.persist_dir = persist_dir
        self.store_type = store_type
        self._graph_store: Any | None = None
        self._initialized = False
        self._entity_count = 0
        self._relationship_count = 0
        self._last_updated: datetime | None = None
        # One-shot guard: hydrate counts from the persisted metadata sidecar the
        # first time they're read on a not-yet-initialized (lazy) store, so
        # `status` reports the on-disk graph size at cold start without forcing a
        # full graph load. Reset by initialize()/clear() which set live counts.
        self._counts_hydrated = False

    @classmethod
    def get_instance(
        cls,
        persist_dir: Path | None = None,
        store_type: str | None = None,
    ) -> "GraphStoreManager":
        """Get or create singleton instance.

        Args:
            persist_dir: Directory for graph persistence.
            store_type: Backend type - only "simple" is supported.

        Returns:
            The singleton GraphStoreManager instance.
        """
        if cls._instance is None:
            if persist_dir is None:
                persist_dir = Path(settings.GRAPH_INDEX_PATH)
            if store_type is None:
                store_type = settings.GRAPH_STORE_TYPE
            cls._instance = cls(persist_dir, store_type)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Used for testing."""
        cls._instance = None

    def initialize(self) -> None:
        """Initialize the graph store.

        Uses SimplePropertyGraphStore with JSON persistence. Any non-"simple"
        ``store_type`` left in an older config is downgraded to "simple" with
        a warning so existing configs keep booting.

        This is a no-op when ENABLE_GRAPH_INDEX is False.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            logger.debug("graph_store.initialize: skipped (ENABLE_GRAPH_INDEX=false)")
            return

        if self._initialized:
            logger.debug(
                "graph_store.initialize: skipped (already initialized)",
                extra={
                    "store_type": self.store_type,
                    "entity_count": self._entity_count,
                    "relationship_count": self._relationship_count,
                },
            )
            return

        logger.info(
            "graph_store.initialize: starting",
            extra={
                "store_type": self.store_type,
                "persist_dir": str(self.persist_dir),
            },
        )

        # Ensure persistence directory exists
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        if self.store_type == "sqlite":
            self._initialize_sqlite_store()
            self._migrate_json_to_sqlite()
            self._update_counts()
        else:
            if self.store_type != "simple":
                logger.warning(
                    "graph_store: backend %r is no longer supported; using "
                    "'simple' (SimplePropertyGraphStore). Update store_type in "
                    "your config to silence this warning.",
                    self.store_type,
                )
                self.store_type = "simple"
            self._initialize_simple_store()

            # Try to load existing graph data
            self.load()

        self._initialized = True
        logger.info(
            "graph_store.initialize: completed",
            extra={
                "store_type": self.store_type,
                "entity_count": self._entity_count,
                "relationship_count": self._relationship_count,
                "persist_dir": str(self.persist_dir),
            },
        )

    def _initialize_sqlite_store(self) -> None:
        """Initialize the persistent SQLite-backed property-graph store."""
        from .sqlite_graph_store import SQLitePropertyGraphStore

        db_path = self.persist_dir / "graph_store.db"
        self._graph_store = SQLitePropertyGraphStore(str(db_path))
        logger.debug("Initialized SQLitePropertyGraphStore at %s", db_path)

    def _migrate_json_to_sqlite(self) -> None:
        """One-time replay of an existing simple JSON graph into SQLite.

        Idempotent: guarded by a ``meta`` flag and skipped when the DB already
        holds edges. The JSON is left in place for rollback safety.
        """
        store = self._graph_store
        if store is None or not hasattr(store, "_conn"):
            return

        already = store._conn.execute(
            "SELECT value FROM meta WHERE key = 'migrated_from_json'"
        ).fetchone()
        if already is not None:
            return
        if store.edge_count(include_invalid=True) > 0:
            # DB already populated some other way — don't double-import.
            store._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) "
                "VALUES ('migrated_from_json', 'skipped')"
            )
            store._conn.commit()
            return

        json_path = self.persist_dir / "graph_store_llamaindex.json"
        if not json_path.exists():
            return

        try:
            from llama_index.core.graph_stores import SimplePropertyGraphStore

            legacy = SimplePropertyGraphStore.from_persist_path(str(json_path))
            nodes = legacy.get()
            names = [
                n.name  # type: ignore[attr-defined]
                for n in nodes
                if getattr(n, "name", None) is not None
            ]
            triplets = legacy.get_triplets(entity_names=names) if names else []
            relations = [t[1] for t in triplets]

            store.upsert_nodes(nodes)
            store.upsert_relations(relations)
            store._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) "
                "VALUES ('migrated_from_json', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            store._conn.commit()
            logger.info(
                "graph_store: migrated JSON → SQLite "
                "(nodes=%d, relations=%d) from %s",
                len(nodes),
                store.edge_count(include_invalid=True),
                json_path,
            )
        except Exception as e:
            logger.warning("graph_store: JSON → SQLite migration failed: %s", e)

    def _initialize_simple_store(self) -> None:
        """Initialize SimplePropertyGraphStore backend."""
        try:
            from llama_index.core.graph_stores import SimplePropertyGraphStore

            self._graph_store = SimplePropertyGraphStore()
            logger.debug("Initialized SimplePropertyGraphStore")
        except ImportError as e:
            logger.warning(f"Failed to import SimplePropertyGraphStore: {e}")
            # Create a minimal fallback store
            self._graph_store = _MinimalGraphStore()
            logger.debug("Using minimal fallback graph store")

    def persist(self) -> None:
        """Persist graph to disk.

        SimplePropertyGraphStore is serialized to JSON.

        This is a no-op when ENABLE_GRAPH_INDEX is False or not initialized.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            return

        if not self._initialized or self._graph_store is None:
            logger.debug("Graph store not initialized, skipping persist")
            return

        if self.store_type == "simple":
            self._persist_simple_store()
        elif self.store_type == "sqlite":
            # The DB file is the persistence; commit pending writes + refresh
            # the sidecar metadata that /health/status and the doctor read.
            self._graph_store.persist()
            self._persist_sqlite_metadata()

        self._last_updated = datetime.now(timezone.utc)
        logger.debug(
            f"Graph persisted: entities={self._entity_count}, "
            f"relationships={self._relationship_count}"
        )

    def _persist_sqlite_metadata(self) -> None:
        """Write the graph_metadata.json sidecar for the SQLite backend."""
        try:
            metadata = {
                "entity_count": self._entity_count,
                "relationship_count": self._relationship_count,
                "last_updated": (
                    self._last_updated.isoformat() if self._last_updated else None
                ),
                "store_type": self.store_type,
            }
            metadata_path = self.persist_dir / "graph_metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except OSError as e:
            logger.error(f"Failed to persist graph metadata: {e}")

    def _persist_simple_store(self) -> None:
        """Persist SimplePropertyGraphStore to JSON."""
        persist_path = self.persist_dir / "graph_store.json"
        llamaindex_persist_path = self.persist_dir / "graph_store_llamaindex.json"

        try:
            # Try LlamaIndex native persistence first
            graph_store = self._graph_store
            if graph_store is not None and hasattr(graph_store, "persist"):
                graph_store.persist(str(llamaindex_persist_path))
                logger.debug(
                    f"Graph persisted via LlamaIndex to {llamaindex_persist_path}"
                )
            elif graph_store is not None and hasattr(graph_store, "_data"):
                # Minimal store fallback - use our own format
                data = getattr(graph_store, "_data", {})
                with open(persist_path, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                logger.debug(f"Graph persisted to {persist_path}")

            # Always persist metadata separately
            metadata = {
                "entity_count": self._entity_count,
                "relationship_count": self._relationship_count,
                "last_updated": (
                    self._last_updated.isoformat() if self._last_updated else None
                ),
                "store_type": self.store_type,
            }
            metadata_path = self.persist_dir / "graph_metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

        except (OSError, TypeError) as e:
            logger.error(f"Failed to persist graph store: {e}")

    def load(self) -> bool:
        """Load graph from disk.

        SimplePropertyGraphStore is loaded from JSON.

        Returns:
            True if loaded successfully, False otherwise.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            return False

        if self._graph_store is None:
            return False

        if self.store_type == "sqlite":
            # DB is already open; counts come straight from SQL.
            self._update_counts()
            return True

        return self._load_simple_store()

    def _load_simple_store(self) -> bool:
        """Load SimplePropertyGraphStore from persisted data."""
        llamaindex_persist_path = self.persist_dir / "graph_store_llamaindex.json"
        persist_path = self.persist_dir / "graph_store.json"
        metadata_path = self.persist_dir / "graph_metadata.json"

        # Load metadata if available
        if metadata_path.exists():
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
                self._entity_count = metadata.get("entity_count", 0)
                self._relationship_count = metadata.get("relationship_count", 0)
                last_updated_str = metadata.get("last_updated")
                if last_updated_str:
                    self._last_updated = datetime.fromisoformat(last_updated_str)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Failed to load graph metadata: {e}")

        # Try LlamaIndex native load first
        if llamaindex_persist_path.exists():
            try:
                from llama_index.core.graph_stores import SimplePropertyGraphStore

                self._graph_store = SimplePropertyGraphStore.from_persist_path(
                    str(llamaindex_persist_path)
                )
                self._update_counts()
                logger.debug(
                    f"Graph loaded from {llamaindex_persist_path}: "
                    f"entities={self._entity_count}, "
                    f"relationships={self._relationship_count}"
                )
                return True
            except Exception as e:
                logger.warning(f"Failed to load via LlamaIndex: {e}")

        # Fall back to minimal store format
        if persist_path.exists():
            try:
                with open(persist_path) as f:
                    data = json.load(f)

                # Restore minimal store data
                graph_store = self._graph_store
                if graph_store is not None and hasattr(graph_store, "_data"):
                    graph_store._data = data
                    if "entities" in data:
                        graph_store._entities = data.get("entities", {})
                    if "relationships" in data:
                        graph_store._relationships = data.get("relationships", [])

                logger.debug(
                    f"Graph loaded from {persist_path}: "
                    f"entities={self._entity_count}, "
                    f"relationships={self._relationship_count}"
                )
                return True
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Failed to load graph store: {e}")
                return False

        logger.debug("No graph data found to load")
        return False

    def _update_counts(self) -> None:
        """Update entity and relationship counts from the graph store."""
        if self._graph_store is None:
            return
        try:
            store = self._graph_store
            if hasattr(store, "node_count") and hasattr(store, "edge_count"):
                # SQLite backend — counts come from cheap COUNT(*) queries.
                self._entity_count = store.node_count()
                self._relationship_count = store.edge_count()
            elif hasattr(store, "get") and hasattr(store, "get_triplets"):
                nodes = store.get()
                self._entity_count = len(nodes)
                entity_names = [
                    n.name for n in nodes if getattr(n, "name", None) is not None
                ]
                if entity_names:
                    triplets = store.get_triplets(entity_names=entity_names)
                else:
                    triplets = []
                # get_triplets can return the same relation once per endpoint
                # name; de-dup on (source_id, label, target_id).
                seen: set[tuple[str, str, str]] = set()
                for subj, rel, obj in triplets:
                    seen.add((subj.name, rel.label, obj.name))
                self._relationship_count = len(seen)
            elif hasattr(store, "_entities"):
                self._entity_count = len(store._entities)
                self._relationship_count = len(getattr(store, "_relationships", []))
        except Exception as e:
            logger.warning(f"Failed to update graph counts: {e}")

    def add_triplet(
        self,
        subject: str,
        predicate: str,
        obj: str,
        subject_type: str | None = None,
        object_type: str | None = None,
        source_chunk_id: str | None = None,
    ) -> bool:
        """Add a triplet to the graph.

        Args:
            subject: Subject entity.
            predicate: Relationship type.
            obj: Object entity.
            subject_type: Optional type for subject.
            object_type: Optional type for object.
            source_chunk_id: Optional source chunk ID.

        Returns:
            True if added successfully, False otherwise.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            return False

        if not self._initialized or self._graph_store is None:
            logger.warning(
                "graph_store.add_triplet: skipped (store not initialized)",
                extra={
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                },
            )
            return False

        try:
            from llama_index.core.graph_stores.types import EntityNode, Relation

            store = self._graph_store

            if not (
                hasattr(store, "upsert_nodes") and hasattr(store, "upsert_relations")
            ):
                # Minimal store fallback (no property-graph API)
                if hasattr(store, "_add_triplet"):
                    store._add_triplet(
                        subject,
                        predicate,
                        obj,
                        subject_type,
                        object_type,
                        source_chunk_id,
                    )
                    self._update_counts()
                    self._last_updated = datetime.now(timezone.utc)
                    return True
                logger.warning(
                    "graph_store.add_triplet: store %s lacks the property-graph "
                    "API (upsert_nodes/upsert_relations) - triplet dropped",
                    type(store).__name__,
                )
                return False

            subject_node = EntityNode(
                name=subject,
                label=subject_type or "Entity",
            )
            object_node = EntityNode(
                name=obj,
                label=object_type or "Entity",
            )
            rel_properties: dict[str, Any] = {}
            if source_chunk_id is not None:
                rel_properties["source_chunk_id"] = source_chunk_id
            relation = Relation(
                label=predicate,
                source_id=subject_node.id,
                target_id=object_node.id,
                properties=rel_properties,
            )

            store.upsert_nodes([subject_node, object_node])
            store.upsert_relations([relation])

            # Counts derive from the store, never fabricated.
            self._update_counts()
            self._last_updated = datetime.now(timezone.utc)

            logger.debug(
                "graph_store.add_triplet: success",
                extra={
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "subject_type": subject_type,
                    "object_type": object_type,
                    "source_chunk_id": source_chunk_id,
                    "total_relationships": self._relationship_count,
                },
            )

            return True
        except Exception as e:
            logger.error(
                "graph_store.add_triplet: failed",
                extra={
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "error": str(e),
                },
            )
            return False

    def invalidate(
        self,
        subject: str,
        predicate: str,
        obj: str,
        at: datetime | None = None,
    ) -> int:
        """Close an edge's validity window (temporal model).

        Returns the number of edges invalidated. No-op (returns 0) on backends
        without temporal support (the ``simple`` store) or when graph indexing
        is disabled.
        """
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return 0
        store = self._graph_store
        if not hasattr(store, "invalidate"):
            return 0
        n = int(store.invalidate(subject, predicate, obj, at))
        if n:
            self._update_counts()
            self._last_updated = datetime.now(timezone.utc)
        return n

    def timeline(self, entity_name: str) -> list[dict[str, Any]]:
        """Return an entity's edge history ordered by validity start.

        Empty list on backends without temporal support or when disabled.
        """
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return []
        store = self._graph_store
        if not hasattr(store, "timeline"):
            return []
        result: list[dict[str, Any]] = store.timeline(entity_name)
        return result

    def find_decision_nodes(self, text: str) -> list[str]:
        """Names of Decision nodes matching ``text`` (Phase 140).

        Empty list on backends without the lookup (e.g. simple) or when disabled.
        """
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return []
        store = self._graph_store
        if not hasattr(store, "find_decision_nodes"):
            return []
        names: list[str] = store.find_decision_nodes(text)
        return names

    def nodes_by_label(
        self,
        label: str,
        contains: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Browse nodes of one label; empty on simple backend or disabled."""
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return []
        store = self._graph_store
        if not hasattr(store, "nodes_by_label"):
            return []
        result: list[dict[str, Any]] = store.nodes_by_label(
            label, contains=contains, limit=limit
        )
        return result

    def timeline_named(self, entity_name: str) -> list[dict[str, Any]]:
        """Name-resolved timeline; empty on simple backend or disabled."""
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return []
        store = self._graph_store
        if not hasattr(store, "timeline_named"):
            return []
        result: list[dict[str, Any]] = store.timeline_named(entity_name)
        return result

    def search_nodes(self, text: str, limit: int = 20) -> list[dict[str, Any]]:
        """Browse-search nodes; empty on simple backend or disabled."""
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return []
        store = self._graph_store
        if not hasattr(store, "search_nodes"):
            return []
        result: list[dict[str, Any]] = store.search_nodes(text, limit=limit)
        return result

    def neighbors(
        self, node_ids: list[str], limit: int = 200
    ) -> dict[str, list[dict[str, Any]]]:
        """Subgraph around nodes; empty on simple backend or disabled."""
        if not settings.ENABLE_GRAPH_INDEX or self._graph_store is None:
            return {"nodes": [], "edges": []}
        store = self._graph_store
        if not hasattr(store, "neighbors"):
            return {"nodes": [], "edges": []}
        result: dict[str, list[dict[str, Any]]] = store.neighbors(node_ids, limit=limit)
        return result

    def clear(self) -> None:
        """Clear all graph data.

        This is a no-op when ENABLE_GRAPH_INDEX is False.
        """
        if not settings.ENABLE_GRAPH_INDEX:
            logger.debug("graph_store.clear: skipped (ENABLE_GRAPH_INDEX=false)")
            return

        prev_entities = self._entity_count
        prev_relationships = self._relationship_count

        if self._graph_store is not None:
            if hasattr(self._graph_store, "clear"):
                self._graph_store.clear()
            elif hasattr(self._graph_store, "_data"):
                self._graph_store._data = {}

        self._entity_count = 0
        self._relationship_count = 0
        self._last_updated = None

        # Remove persisted data
        persist_path = self.persist_dir / "graph_store.json"
        if persist_path.exists():
            persist_path.unlink()

        logger.info(
            "graph_store.clear: completed",
            extra={
                "previous_entities": prev_entities,
                "previous_relationships": prev_relationships,
                "persist_dir": str(self.persist_dir),
            },
        )

    @property
    def is_initialized(self) -> bool:
        """Check if the graph store is initialized."""
        return self._initialized

    def _hydrate_counts_from_metadata(self) -> None:
        """Populate counts from the ``graph_metadata.json`` sidecar (best-effort).

        Both backends write this sidecar on persist. When the store is still
        lazy (not ``initialize()``-d), the in-memory counts are 0 even though a
        graph is persisted on disk — making ``status`` report ``0 entities`` at
        cold start. Reading the sidecar once lets the reported counts reflect the
        on-disk graph without a full load. ``initialize()`` later overwrites
        these with live counts from the store.
        """
        if self._initialized or self._counts_hydrated:
            return
        self._counts_hydrated = True
        metadata_path = self.persist_dir / "graph_metadata.json"
        try:
            if metadata_path.is_file():
                data = json.loads(metadata_path.read_text())
                self._entity_count = int(data.get("entity_count", 0) or 0)
                self._relationship_count = int(data.get("relationship_count", 0) or 0)
        except (OSError, ValueError):
            pass

    @property
    def entity_count(self) -> int:
        """Return number of entities in graph."""
        self._hydrate_counts_from_metadata()
        return self._entity_count

    @property
    def relationship_count(self) -> int:
        """Return number of relationships in graph."""
        self._hydrate_counts_from_metadata()
        return self._relationship_count

    @property
    def last_updated(self) -> datetime | None:
        """Return timestamp of last update."""
        return self._last_updated

    @property
    def graph_store(self) -> Any | None:
        """Return the underlying graph store instance."""
        return self._graph_store


class _MinimalGraphStore:
    """Minimal fallback graph store when LlamaIndex is not available.

    Provides basic in-memory graph storage with JSON serialization.
    """

    def __init__(self) -> None:
        """Initialize minimal graph store."""
        self._data: dict[str, Any] = {
            "entities": {},
            "relationships": [],
        }
        self._entities: dict[str, dict[str, Any]] = {}
        self._relationships: list[dict[str, Any]] = []

    def _add_triplet(
        self,
        subject: str,
        predicate: str,
        obj: str,
        subject_type: str | None = None,
        object_type: str | None = None,
        source_chunk_id: str | None = None,
    ) -> None:
        """Add a triplet to the minimal store."""
        # Add entities
        if subject not in self._entities:
            self._entities[subject] = {"name": subject, "type": subject_type}
        if obj not in self._entities:
            self._entities[obj] = {"name": obj, "type": object_type}

        # Add relationship
        self._relationships.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "source_chunk_id": source_chunk_id,
            }
        )

        # Update data dict
        self._data["entities"] = self._entities
        self._data["relationships"] = self._relationships

    def clear(self) -> None:
        """Clear all data."""
        self._data = {"entities": {}, "relationships": []}
        self._entities = {}
        self._relationships = []


# Module-level singleton access
_graph_store_manager: GraphStoreManager | None = None


def get_graph_store_manager(
    persist_dir: Path | None = None,
    store_type: str | None = None,
) -> GraphStoreManager:
    """Get the global graph store manager instance.

    Args:
        persist_dir: Directory for graph persistence.
        store_type: Backend type - only "simple" is supported.

    Returns:
        The singleton GraphStoreManager instance.
    """
    global _graph_store_manager
    if _graph_store_manager is None:
        _graph_store_manager = GraphStoreManager.get_instance(persist_dir, store_type)
    return _graph_store_manager


def initialize_graph_store(
    persist_dir: Path | None = None,
    store_type: str | None = None,
) -> GraphStoreManager:
    """Initialize and return the global graph store manager.

    Args:
        persist_dir: Directory for graph persistence.
        store_type: Backend type - only "simple" is supported.

    Returns:
        The initialized GraphStoreManager instance.
    """
    manager = get_graph_store_manager(persist_dir, store_type)
    manager.initialize()
    return manager


def reset_graph_store_manager() -> None:
    """Reset the global graph store manager. Used for testing."""
    global _graph_store_manager
    _graph_store_manager = None
    GraphStoreManager.reset_instance()

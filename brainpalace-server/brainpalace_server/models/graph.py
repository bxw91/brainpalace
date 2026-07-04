"""Models for GraphRAG feature (Feature 113).

Defines Pydantic models for graph entities, relationships, and status.
All models are configured with frozen=True for immutability.
"""

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

# Entity Type Schema (SCHEMA-01, SCHEMA-02, SCHEMA-03)

# Code entity types
CodeEntityType = Literal[
    "Package",  # Top-level package
    "Module",  # EXTERNAL importable namespace (os, pytest); repo files are File
    "Class",  # Class definition
    "Method",  # Class method
    "Function",  # Standalone function
    "Interface",  # Interface/Protocol
    "Enum",  # Enumeration type
    "File",  # Repo source file (Plan 3, §1)
    "Folder",  # Repo directory (Plan 3, §1)
    "Decorator",  # Decorator applied to a symbol (Plan 3, §5b)
]

# Documentation entity types
DocEntityType = Literal[
    "DesignDoc",  # Design documents
    "UserDoc",  # User documentation
    "PRD",  # Product requirements
    "Runbook",  # Operational runbooks
    "README",  # README files
    "APIDoc",  # API documentation
]

# Infrastructure entity types
InfraEntityType = Literal[
    "Service",  # Microservice
    "Endpoint",  # API endpoint
    "Database",  # Database
    "ConfigFile",  # Configuration file
]

# Session knowledge-graph entity types (Phase 100). These label the nodes
# produced by session triplet extraction; types are derived server-side from
# the relation (see services/session_triplet_types.py).
SessionEntityType = Literal[
    "Decision",  # A choice made during a session
    "Error",  # An error/bug encountered
    "Session",  # An AI-coding session
    "Tool",  # A tool/command run in a session
    "File",  # A file edited/created/read
    "Task",  # A task/phase of work
]

# Git entity types (Plan C). Nodes produced by the deterministic commit-graph
# writer (indexing/git_graph.py); domain 'git'.
GitEntityType = Literal[
    "Commit",  # One git commit (id git-commit:<sha>)
    "Author",  # A commit author, keyed by email (id git-author:<email>)
]

# Combined entity type (code + doc + infra + session)
EntityType = Literal[
    # Code (7 types)
    "Package",
    "Module",
    "Class",
    "Method",
    "Function",
    "Interface",
    "Enum",
    # Code (Plan 3 additions)
    "Folder",
    "Decorator",
    # Documentation (6 types)
    "DesignDoc",
    "UserDoc",
    "PRD",
    "Runbook",
    "README",
    "APIDoc",
    # Infrastructure (4 types)
    "Service",
    "Endpoint",
    "Database",
    "ConfigFile",
    # Session (6 types)
    "Decision",
    "Error",
    "Session",
    "Tool",
    "File",
    "Task",
    # Git (2 types, Plan C)
    "Commit",
    "Author",
]

# Relationship types (12 predicates)
RelationshipType = Literal[
    "calls",  # Function/method invocation
    "extends",  # Class inheritance
    "implements",  # Interface implementation
    "references",  # Non-call type use / documentation references code
    "depends_on",  # Package/module dependency
    "imports",  # Import statement
    "contains",  # Containment relationship
    "defined_in",  # Symbol defined in file
    "decorated_by",  # Symbol decorated by a decorator (Plan 3, §5b)
    "handled_by",  # Endpoint handled by a function (Plan 3, §5b)
    "modifies",  # Commit modifies File (Plan C)
    "authored_by",  # Commit authored_by Author (Plan C)
]

# Runtime constants for validation and iteration
ENTITY_TYPES: list[str] = list(get_args(EntityType))
RELATIONSHIP_TYPES: list[str] = list(get_args(RelationshipType))
CODE_ENTITY_TYPES: list[str] = list(get_args(CodeEntityType))
DOC_ENTITY_TYPES: list[str] = list(get_args(DocEntityType))
INFRA_ENTITY_TYPES: list[str] = list(get_args(InfraEntityType))
SESSION_ENTITY_TYPES: list[str] = list(get_args(SessionEntityType))
GIT_ENTITY_TYPES: list[str] = list(get_args(GitEntityType))

# LSP cross-reference relations (Phase 150). Closed vocabulary for the typed
# symbol graph produced from language-server queries.
LSP_RELATIONS: list[str] = [
    "calls",  # symbol invokes another symbol
    "called-by",  # inverse of calls
    "references",  # symbol references another (non-call use)
    "extends",  # class extends a base class
    "implements",  # class implements an interface/protocol
    "imports",  # module/symbol imports another
]


def symbol_id(file_path: str, fqname: str) -> str:
    """Canonical LSP symbol identifier ``file:fqname`` (Phase 150).

    POSIX-normalised path; both parts required (empty string if either missing),
    so callers can cheaply skip un-addressable symbols. Phase 140's
    canonicalisation can align file paths to these.
    """
    fp = (file_path or "").strip().replace("\\", "/")
    fq = (fqname or "").strip()
    if not fp or not fq:
        return ""
    return f"{fp}:{fq}"


# AST symbol type mapping to schema entity types
SYMBOL_TYPE_MAPPING: dict[str, str] = {
    "package": "Package",
    "module": "Module",
    "class": "Class",
    "method": "Method",
    "function": "Function",
    "interface": "Interface",
    "enum": "Enum",
    "file": "File",
    "folder": "Folder",
    "decorator": "Decorator",
}

# Comprehensive case-insensitive mapping for ALL entity types.
# .capitalize() breaks acronyms like README and APIDoc, so we use
# an explicit lookup table built from get_args(EntityType).
ENTITY_TYPE_NORMALIZE: dict[str, str] = {t.lower(): t for t in ENTITY_TYPES}
# Also merge SYMBOL_TYPE_MAPPING for AST symbol types
ENTITY_TYPE_NORMALIZE.update(SYMBOL_TYPE_MAPPING)


def normalize_entity_type(raw_type: str | None) -> str | None:
    """Normalize a raw entity type string to schema EntityType.

    Uses explicit mapping to preserve acronyms (README, APIDoc, PRD).
    Returns None if input is None, returns original string if no mapping found.

    Args:
        raw_type: Raw entity type string (may be lowercase, mixed case, etc.)

    Returns:
        Normalized entity type from schema, or original if not found, or None.

    Examples:
        >>> normalize_entity_type("function")
        "Function"
        >>> normalize_entity_type("CLASS")
        "Class"
        >>> normalize_entity_type("readme")
        "README"
        >>> normalize_entity_type("apidoc")
        "APIDoc"
        >>> normalize_entity_type(None)
        None
        >>> normalize_entity_type("CustomType")
        "CustomType"
    """
    if raw_type is None:
        return None
    # Exact match first (already correct case)
    if raw_type in ENTITY_TYPES:
        return raw_type
    # Case-insensitive lookup via explicit mapping
    mapped = ENTITY_TYPE_NORMALIZE.get(raw_type.lower())
    if mapped:
        return mapped
    return raw_type  # Fallback: keep original for flexibility


class GraphTriple(BaseModel):
    """Represents a subject-predicate-object triple in the knowledge graph.

    Triples are the fundamental unit of knowledge representation in GraphRAG.
    They capture relationships between entities extracted from documents.

    Attributes:
        subject: The subject entity (e.g., "FastAPI").
        subject_type: Optional type classification (e.g., "Framework").
        predicate: The relationship type (e.g., "uses").
        object: The object entity (e.g., "Pydantic").
        object_type: Optional type classification (e.g., "Library").
        source_chunk_id: Optional ID of the source document chunk.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "subject": "FastAPI",
                    "subject_type": "Framework",
                    "predicate": "uses",
                    "object": "Pydantic",
                    "object_type": "Library",
                    "source_chunk_id": "chunk_abc123",
                },
                {
                    "subject": "UserController",
                    "subject_type": "Class",
                    "predicate": "calls",
                    "object": "authenticate_user",
                    "object_type": "Function",
                    "source_chunk_id": "chunk_def456",
                },
            ]
        },
    )

    subject: str = Field(
        ...,
        min_length=1,
        description="Subject entity in the triple",
    )
    subject_type: str | None = Field(
        default=None,
        description="Type classification for subject entity",
    )
    predicate: str = Field(
        ...,
        min_length=1,
        description="Relationship type connecting subject to object",
    )
    object: str = Field(
        ...,
        min_length=1,
        description="Object entity in the triple",
    )
    object_type: str | None = Field(
        default=None,
        description="Type classification for object entity",
    )
    source_chunk_id: str | None = Field(
        default=None,
        description="ID of the source document chunk",
    )
    domain: str = Field(default="code", description="Domain tag (seam #1)")
    source: str | None = Field(default=None, description="Provenance: source kind")
    source_id: str | None = Field(default=None, description="Provenance: source id")
    ingested_at: str | None = Field(default=None, description="Provenance: ISO ts")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="0..1")
    subject_id: str | None = None
    object_id: str | None = None
    subject_name: str | None = None
    object_name: str | None = None
    source_file: str | None = None

    @property
    def effective_subject_id(self) -> str:
        return self.subject_id or self.subject

    @property
    def effective_object_id(self) -> str:
        return self.object_id or self.object


class GraphEntity(BaseModel):
    """Represents an entity node in the knowledge graph.

    Entities are the nodes in the graph, representing concepts,
    code elements, or other named items extracted from documents.

    Attributes:
        name: Unique name/identifier of the entity.
        entity_type: Classification type (e.g., "Class", "Function", "Concept").
        description: Optional description of the entity.
        source_chunk_ids: List of source chunk IDs where entity appears.
        properties: Additional metadata properties.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "name": "VectorStoreManager",
                    "entity_type": "Class",
                    "description": "Manages Chroma vector store operations",
                    "source_chunk_ids": ["chunk_001", "chunk_002"],
                    "properties": {"module": "storage.vector_store"},
                },
            ]
        },
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Unique name/identifier of the entity",
    )
    entity_type: str | None = Field(
        default=None,
        description="Classification type for the entity",
    )
    description: str | None = Field(
        default=None,
        description="Description of the entity",
    )
    source_chunk_ids: list[str] = Field(
        default_factory=list,
        description="List of source chunk IDs where entity appears",
    )
    properties: dict[str, str] = Field(
        default_factory=dict,
        description="Additional metadata properties",
    )
    domain: str = Field(default="code", description="Domain tag (seam #1)")
    source: str | None = Field(default=None, description="Provenance: source kind")
    source_id: str | None = Field(default=None, description="Provenance: source id")
    ingested_at: str | None = Field(default=None, description="Provenance: ISO ts")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="0..1")


class GraphIndexStatus(BaseModel):
    """Status of the graph index.

    Provides information about the graph index state,
    including whether it's enabled, initialized, and statistics.

    Attributes:
        enabled: Whether graph indexing is enabled.
        initialized: Whether the graph store is initialized.
        entity_count: Number of entities in the graph.
        relationship_count: Number of relationships in the graph.
        last_updated: Timestamp of last graph update.
        store_type: Type of graph store backend.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "initialized": True,
                    "entity_count": 150,
                    "relationship_count": 320,
                    "last_updated": "2024-12-15T10:30:00Z",
                    "store_type": "simple",
                },
                {
                    "enabled": False,
                    "initialized": False,
                    "entity_count": 0,
                    "relationship_count": 0,
                    "last_updated": None,
                    "store_type": "simple",
                },
            ]
        },
    )

    enabled: bool = Field(
        default=False,
        description="Whether graph indexing is enabled",
    )
    initialized: bool = Field(
        default=False,
        description="Whether the graph store is initialized",
    )
    entity_count: int = Field(
        default=0,
        ge=0,
        description="Number of entities in the graph",
    )
    relationship_count: int = Field(
        default=0,
        ge=0,
        description="Number of relationships in the graph",
    )
    last_updated: datetime | None = Field(
        default=None,
        description="Timestamp of last graph update",
    )
    store_type: str = Field(
        default="simple",
        description="Type of graph store backend (only 'simple' is supported)",
    )


class GraphQueryContext(BaseModel):
    """Context information from graph-based retrieval.

    Contains additional context extracted from the knowledge graph
    during query processing.

    Attributes:
        related_entities: List of related entity names.
        relationship_paths: List of relationship paths as strings.
        subgraph_triplets: Relevant triplets from the graph.
        graph_score: Score from graph-based retrieval.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "related_entities": ["FastAPI", "Pydantic", "Uvicorn"],
                    "relationship_paths": [
                        "FastAPI -> uses -> Pydantic",
                        "FastAPI -> runs_on -> Uvicorn",
                    ],
                    "subgraph_triplets": [
                        {
                            "subject": "FastAPI",
                            "predicate": "uses",
                            "object": "Pydantic",
                        },
                    ],
                    "graph_score": 0.85,
                },
            ]
        },
    )

    related_entities: list[str] = Field(
        default_factory=list,
        description="List of related entity names",
    )
    relationship_paths: list[str] = Field(
        default_factory=list,
        description="Relationship paths as formatted strings",
    )
    subgraph_triplets: list[GraphTriple] = Field(
        default_factory=list,
        description="Relevant triplets from the graph",
    )
    graph_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Score from graph-based retrieval",
    )

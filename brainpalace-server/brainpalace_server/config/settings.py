"""Application configuration using Pydantic settings."""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    DEBUG: bool = False

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    # Default embedding model. Supported models + cost per 1M tokens:
    # see docs/PROVIDER_CONFIGURATION.md. Changing this invalidates the index.
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_DIMENSIONS: int = 3072

    # Anthropic Configuration
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"  # Claude 4.5 Haiku (latest)

    # Chroma Configuration
    # Legacy CWD-relative defaults — only used when state_dir resolution
    # fails completely. Normal operation resolves paths via storage_paths.py.
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    BM25_INDEX_PATH: str = "./bm25_index"
    COLLECTION_NAME: str = "brainpalace_collection"

    # Chunking Configuration
    DEFAULT_CHUNK_SIZE: int = 512
    DEFAULT_CHUNK_OVERLAP: int = 50
    MAX_CHUNK_SIZE: int = 2048
    MIN_CHUNK_SIZE: int = 128

    # Query Configuration
    DEFAULT_TOP_K: int = 5
    MAX_TOP_K: int = 50
    DEFAULT_SIMILARITY_THRESHOLD: float = 0.7

    # Rate Limiting
    EMBEDDING_BATCH_SIZE: int = 100

    # Multi-instance Configuration
    BRAINPALACE_STATE_DIR: str | None = None  # Override state directory
    BRAINPALACE_MODE: str = "project"  # "project" or "shared"

    # Strict Mode Configuration
    BRAINPALACE_STRICT_MODE: bool = False  # Fail on critical validation errors

    # Storage Backend Configuration (Phase 5)
    BRAINPALACE_STORAGE_BACKEND: str = (
        ""  # Empty = use YAML config; "chroma" or "postgres" overrides YAML
    )

    # Curated Memory Configuration (Phase 030 — memory-namespace)
    MEMORY_ENABLED: bool = True  # Master switch for the curated memory namespace
    # Markdown source-of-truth path. Empty => <project_root>/BRAINPALACE_MEMORY.md
    # (git-tracked by design; see docs/MEMORY.md + ADR 0001). Override via the
    # MEMORY_PATH env var or config.
    MEMORY_PATH: str = ""
    MEMORY_COLLECTION: str = "brainpalace_memories"  # Chroma shadow-index name
    MEMORY_CHAR_CAP: int = 8000  # Hard cap on the markdown file (forces curation)
    MEMORY_BOOST: float = 1.5  # Score multiplier for memory hits merged into query
    MEMORY_RECALL_K: int = 3  # Memory hits considered in the query boost pass
    MEMORY_MIN_SCORE: float = 0.35  # Relevance floor before a memory can boost in

    # Session-start context injection (Phase 035 — memory-injection)
    CONTEXT_ENABLED: bool = True  # Master switch for the session-start block
    CONTEXT_BUDGET_TOKENS: int = 3000  # Frozen-snapshot budget (~chars/4 estimate)

    # GraphRAG Configuration (Feature 113)
    # Master switch for graph indexing. On by default; `brainpalace init` also
    # writes graphrag.enabled=true into the project config.yaml.
    ENABLE_GRAPH_INDEX: bool = True
    # "sqlite" (default: persistent, incrementally-writable, temporal-validity —
    # Phase 090) or "simple" (in-memory, JSON-persisted, zero-setup, no temporal).
    GRAPH_STORE_TYPE: str = "sqlite"
    # Legacy CWD-relative default — normal operation resolves via storage_paths.py.
    GRAPH_INDEX_PATH: str = "./graph_index"  # Path for graph persistence
    GRAPH_EXTRACTION_MODEL: str = "claude-haiku-4-5"  # Model for entity extraction
    GRAPH_MAX_TRIPLETS_PER_CHUNK: int = 10  # Max triplets per document chunk
    GRAPH_USE_CODE_METADATA: bool = True  # Use AST metadata for code entities
    GRAPH_TRAVERSAL_DEPTH: int = 2  # Depth for graph traversal in queries
    GRAPH_RRF_K: int = 60  # Reciprocal Rank Fusion constant for multi-retrieval

    # Job Queue Configuration (Feature 115)
    BRAINPALACE_MAX_QUEUE: int = 100  # Max pending jobs in queue
    BRAINPALACE_JOB_TIMEOUT: int = 7200  # Job timeout in seconds (2 hours)
    BRAINPALACE_MAX_RETRIES: int = 3  # Max retries for failed jobs
    BRAINPALACE_CHECKPOINT_INTERVAL: int = 50  # Progress checkpoint every N files
    BRAINPALACE_WATCH_DEBOUNCE_SECONDS: int = 30  # File watcher debounce (Phase 15)
    # Per-folder minimum interval between two watcher-triggered enqueues.
    # Suppresses delayed inotify replays after a prior job already transitioned
    # RUNNING→DONE (so dedupe_key no longer matches). Set to 0 to disable.
    BRAINPALACE_WATCH_POST_ENQUEUE_COOLDOWN_SECONDS: int = 10
    # When True (default), the server reads project-local `.gitignore` files
    # at startup and honours them during indexing + file watching. Set to
    # False to ignore .gitignore entirely (fall back to exclude_patterns +
    # DEFAULT_EXCLUDE_PATTERNS only). See Phase H.
    BRAINPALACE_HONOR_GITIGNORE: bool = True

    # Embedding Cache Configuration (Phase 16)
    EMBEDDING_CACHE_MAX_DISK_MB: int = 500  # Max disk size in MB
    EMBEDDING_CACHE_MAX_MEM_ENTRIES: int = 10_000  # In-memory LRU size
    EMBEDDING_CACHE_PERSIST_STATS: bool = False  # Persist hit/miss across restarts

    # Query Cache Configuration (Phase 17)
    QUERY_CACHE_TTL: int = 3600  # TTL in seconds (1 hour)
    QUERY_CACHE_MAX_SIZE: int = 256  # Max cached query results

    # Tokenizer Configuration
    # When True (default), tiktoken's encode() is called with
    # disallowed_special=() so that text containing literal special-token
    # strings like "<|endoftext|>" (common in LLM/inference docs) doesn't
    # crash indexing. Set False to restore the historical strict behavior
    # that raises ValueError on such tokens. Fixes issue #114.
    ALLOW_SPECIAL_TOKENS_IN_TEXT: bool = True

    # Reranking Configuration (Feature 123)
    ENABLE_RERANKING: bool = False  # Off by default
    RERANKER_PROVIDER: str = "sentence-transformers"  # or "ollama"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    RERANKER_TOP_K_MULTIPLIER: int = 10  # Retrieve top_k * this for Stage 1
    RERANKER_MAX_CANDIDATES: int = 100  # Cap on Stage 1 candidates
    # Note: CrossEncoder.rank() handles batching internally, no batch_size config needed

    # Time-decay ranking (Phase 110): multiply each result's score by an
    # exponential age factor 0.5 ** (age_days / half_life) so newer chunks rank
    # higher. 0 disables. Per-query override via QueryRequest.time_decay.
    BRAINPALACE_TIME_DECAY_HALF_LIFE_DAYS: float = 90.0

    # Cross-session linking (Phase 140).
    # Promote durable session decisions into the curated-memory namespace (030).
    BRAINPALACE_PROMOTE_DECISIONS: bool = True
    # Ranking multiplier applied to results tied to a superseded (stale)
    # decision. 1.0 = off; lower = stronger penalty.
    BRAINPALACE_STALE_DECISION_PENALTY: float = 0.5

    # LSP cross-references (Phase 150). Comma-separated language allow-list
    # (e.g. "python,typescript"). Empty = the whole LSP subsystem is inert.
    # Requires the per-language server binary installed (fail-soft if absent).
    BRAINPALACE_LSP_LANGUAGES: str = ""

    # Compute query mode (Phase 0 — compute-foundation). No switches: the mode
    # is always selectable and empty without records; records are extracted
    # whenever session extraction runs (gated by extraction.mode).
    COMPUTE_MIN_CONFIDENCE: float = Field(default=0.7, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(
        env_file=[
            ".env",  # Current directory
            Path(__file__).parent.parent.parent / ".env",  # Project root
            Path(__file__).parent.parent / ".env",  # brainpalace-server directory
        ],
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignore env vars not in this model (e.g. GEMINI_API_KEY)
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()

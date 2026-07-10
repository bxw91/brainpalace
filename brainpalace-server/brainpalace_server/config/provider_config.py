"""Provider configuration models and YAML loader.

This module provides Pydantic models for embedding and summarization
provider configuration, and functions to load configuration from YAML files.
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from brainpalace_server.providers.base import (
    EmbeddingProviderType,
    RerankerProviderType,
    SummarizationProviderType,
)

logger = logging.getLogger(__name__)


# Provider -> conventional API-key env var. Used to resolve the right env var
# when the user selects a provider but leaves api_key_env unset, so an
# openai-only user isn't told to "Set ANTHROPIC_API_KEY". None = no key needed.
_EMBEDDING_KEY_ENV: dict[EmbeddingProviderType, str | None] = {
    EmbeddingProviderType.OPENAI: "OPENAI_API_KEY",
    EmbeddingProviderType.COHERE: "COHERE_API_KEY",
    EmbeddingProviderType.OLLAMA: None,
}

_SUMMARIZATION_KEY_ENV: dict[SummarizationProviderType, str | None] = {
    SummarizationProviderType.ANTHROPIC: "ANTHROPIC_API_KEY",
    SummarizationProviderType.OPENAI: "OPENAI_API_KEY",
    SummarizationProviderType.GEMINI: "GEMINI_API_KEY",
    SummarizationProviderType.GROK: "XAI_API_KEY",
    SummarizationProviderType.OLLAMA: None,
}


class ValidationSeverity(str, Enum):
    """Severity level for validation errors."""

    CRITICAL = "critical"  # Blocks startup in strict mode
    WARNING = "warning"  # Logged but doesn't block startup


@dataclass
class ValidationError:
    """A validation error with severity and details."""

    message: str
    severity: ValidationSeverity
    provider_type: str  # "embedding", "summarization", "reranker"
    field: str = ""  # Optional field name

    def __str__(self) -> str:
        prefix = (
            "[CRITICAL]"
            if self.severity == ValidationSeverity.CRITICAL
            else "[WARNING]"
        )
        return f"{prefix} {self.provider_type}: {self.message}"


class EmbeddingConfig(BaseModel):
    """Configuration for embedding provider."""

    provider: EmbeddingProviderType = Field(
        default=EmbeddingProviderType.OPENAI,
        description="Embedding provider to use",
    )
    model: str = Field(
        default="text-embedding-3-large",
        description=(
            "Embedding model name. See docs/PROVIDER_CONFIGURATION.md for "
            "supported models per provider and their relative cost. Changing "
            "the model invalidates the existing index."
        ),
    )
    api_key: str | None = Field(
        default=None,
        description="API key (alternative to api_key_env for local config files)",
    )
    api_key_env: str | None = Field(
        default=None,
        description=(
            "Environment variable name containing API key. When unset, the "
            "conventional var for the selected provider is used "
            "(openai->OPENAI_API_KEY, cohere->COHERE_API_KEY)."
        ),
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL (for Ollama or compatible APIs)",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific parameters",
    )

    model_config = {"use_enum_values": True}

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, v: Any) -> EmbeddingProviderType:
        """Convert string to enum if needed."""
        if isinstance(v, str):
            return EmbeddingProviderType(v.lower())
        if isinstance(v, EmbeddingProviderType):
            return v
        return EmbeddingProviderType(v)

    def resolved_api_key_env(self) -> str | None:
        """Env var holding the API key, explicit or provider-derived.

        Returns the user's ``api_key_env`` if set, else the conventional
        var for the selected provider (None for providers needing no key).
        """
        if self.api_key_env:
            return self.api_key_env
        provider = EmbeddingProviderType(self.provider)
        return _EMBEDDING_KEY_ENV.get(provider)

    def get_api_key(self) -> str | None:
        """Resolve API key from config or environment variable.

        Resolution order:
        1. api_key field in config (direct value)
        2. Environment variable (explicit api_key_env or provider-derived)

        Returns:
            API key value or None if not found/not needed
        """
        if self.provider == EmbeddingProviderType.OLLAMA:
            return None  # Ollama doesn't need API key
        # Check direct api_key first
        if self.api_key:
            return self.api_key
        # Fall back to environment variable
        env_var = self.resolved_api_key_env()
        if env_var:
            return os.getenv(env_var)
        return None

    def get_base_url(self) -> str | None:
        """Get base URL with defaults for specific providers.

        Returns:
            Base URL for the provider
        """
        if self.base_url:
            return self.base_url
        if self.provider == EmbeddingProviderType.OLLAMA:
            return "http://localhost:11434/v1"
        return None


class SummarizationConfig(BaseModel):
    """Configuration for summarization provider."""

    provider: SummarizationProviderType = Field(
        default=SummarizationProviderType.ANTHROPIC,
        description="Summarization provider to use",
    )
    model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model name for summarization",
    )
    api_key: str | None = Field(
        default=None,
        description="API key (alternative to api_key_env for local config files)",
    )
    api_key_env: str | None = Field(
        default=None,
        description=(
            "Environment variable name containing API key. When unset, the "
            "conventional var for the selected provider is used "
            "(anthropic->ANTHROPIC_API_KEY, openai->OPENAI_API_KEY, "
            "gemini->GEMINI_API_KEY, grok->XAI_API_KEY)."
        ),
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL (for Grok or Ollama)",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific parameters (max_tokens, temperature)",
    )

    model_config = {"use_enum_values": True}

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, v: Any) -> SummarizationProviderType:
        """Convert string to enum if needed."""
        if isinstance(v, str):
            return SummarizationProviderType(v.lower())
        if isinstance(v, SummarizationProviderType):
            return v
        return SummarizationProviderType(v)

    def resolved_api_key_env(self) -> str | None:
        """Env var holding the API key, explicit or provider-derived.

        Returns the user's ``api_key_env`` if set, else the conventional
        var for the selected provider (None for providers needing no key).
        """
        if self.api_key_env:
            return self.api_key_env
        provider = SummarizationProviderType(self.provider)
        return _SUMMARIZATION_KEY_ENV.get(provider)

    def get_api_key(self) -> str | None:
        """Resolve API key from config or environment variable.

        Resolution order:
        1. api_key field in config (direct value)
        2. Environment variable (explicit api_key_env or provider-derived)

        Returns:
            API key value or None if not found/not needed
        """
        if self.provider == SummarizationProviderType.OLLAMA:
            return None  # Ollama doesn't need API key
        # Check direct api_key first
        if self.api_key:
            return self.api_key
        # Fall back to environment variable
        env_var = self.resolved_api_key_env()
        if env_var:
            return os.getenv(env_var)
        return None

    def get_base_url(self) -> str | None:
        """Get base URL with defaults for specific providers.

        Returns:
            Base URL for the provider
        """
        if self.base_url:
            return self.base_url
        if self.provider == SummarizationProviderType.OLLAMA:
            return "http://localhost:11434/v1"
        if self.provider == SummarizationProviderType.GROK:
            return "https://api.x.ai/v1"
        return None


class RerankerConfig(BaseModel):
    """Configuration for reranking provider."""

    enabled: bool = Field(
        default=False,
        description=(
            "Enable two-stage reranking (local cross-encoder; adds query "
            "latency, no API cost). OFF by default; the ENABLE_RERANKING env "
            "var overrides this when set."
        ),
    )
    provider: RerankerProviderType = Field(
        default=RerankerProviderType.SENTENCE_TRANSFORMERS,
        description="Reranking provider to use",
    )
    model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Model name for reranking",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL (for Ollama)",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific parameters (batch_size, etc.)",
    )

    model_config = {"use_enum_values": True}

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, v: Any) -> RerankerProviderType:
        """Convert string to enum if needed."""
        if isinstance(v, str):
            return RerankerProviderType(v.lower())
        if isinstance(v, RerankerProviderType):
            return v
        return RerankerProviderType(v)

    def get_base_url(self) -> str | None:
        """Get base URL with defaults for specific providers.

        Returns:
            Base URL for the provider
        """
        if self.base_url:
            return self.base_url
        if self.provider == RerankerProviderType.OLLAMA:
            return "http://localhost:11434"
        return None


class StorageConfig(BaseModel):
    """Configuration for storage backend selection."""

    backend: str = Field(
        default="chroma",
        description="Storage backend: 'chroma' or 'postgres'",
    )
    postgres: dict[str, Any] = Field(
        default_factory=dict,
        description="PostgreSQL connection parameters (Phase 6)",
    )

    @field_validator("backend", mode="before")
    @classmethod
    def validate_backend(cls, v: Any) -> str:
        """Validate and normalize backend value."""
        valid = {"chroma", "postgres"}
        val = str(v).lower()
        if val not in valid:
            raise ValueError(f"Invalid storage backend '{v}'. Must be one of: {valid}")
        return val


class GraphRAGConfig(BaseModel):
    """GraphRAG configuration parsed from the `graphrag:` section of config.yaml.

    Every field is Optional with a None default: an absent YAML key stays
    None so the lifespan override (Phase G) only applies keys the user
    actually set. Mirrors the GRAPH_* env vars in config/settings.py.
    """

    enabled: bool | None = Field(
        default=None, description="Master switch for graph indexing"
    )
    store_type: str | None = Field(
        default=None,
        description=(
            "Graph store backend; 'sqlite' (persistent, default) or "
            "'simple' (in-memory, JSON-persisted)"
        ),
    )
    index_path: str | None = Field(
        default=None, description="Path for graph persistence"
    )
    extraction_model: str | None = Field(
        default=None, description="Model for entity extraction"
    )
    max_triplets_per_chunk: int | None = Field(
        default=None, description="Max triplets per document chunk"
    )
    use_code_metadata: bool | None = Field(
        default=None, description="Use AST metadata for code entities"
    )
    traversal_depth: int | None = Field(
        default=None, description="Depth for graph traversal in queries"
    )
    rrf_k: int | None = Field(
        default=None, description="Reciprocal Rank Fusion constant for multi-retrieval"
    )


class ComputeConfig(BaseModel):
    """`compute:` section of config.yaml. All-None so an absent key leaves the
    Settings default; the lifespan override copies set keys onto the flat
    COMPUTE_MIN_CONFIDENCE (env wins).

    Compute query mode has no switches — like bm25/vector it is always
    selectable and returns empty when no records exist (unlike graph, which is
    gated by ENABLE_GRAPH_INDEX). Records are extracted whenever session
    extraction runs (gated by extraction.mode); there is no separate
    record-extraction toggle. ``min_confidence`` only tunes which stored records
    enter aggregates."""

    min_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Min record confidence summed by default compute",
    )


class ProviderSettings(BaseModel):
    """Top-level provider configuration."""

    embedding: EmbeddingConfig = Field(
        default_factory=EmbeddingConfig,
        description="Embedding provider configuration",
    )
    summarization: SummarizationConfig = Field(
        default_factory=SummarizationConfig,
        description="Summarization provider configuration",
    )
    reranker: RerankerConfig = Field(
        default_factory=RerankerConfig,
        description="Reranking provider configuration (optional)",
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Storage backend configuration",
    )
    graphrag: GraphRAGConfig = Field(
        default_factory=GraphRAGConfig,
        description="GraphRAG configuration (Phase G)",
    )
    compute: ComputeConfig = Field(
        default_factory=ComputeConfig,
        description="Compute query mode configuration (Phase 1)",
    )


def _find_project_config_file() -> Path | None:
    """Find the PROJECT-scoped config file (never the global XDG one).

    Search order (project layer of ``code < global < project``):
    1. BRAINPALACE_CONFIG environment variable
    2. State directory config.yaml (BRAINPALACE_STATE_DIR / DOC_SERVE_STATE_DIR)
    3. Current directory config.yaml
    4. Walk up from CWD: .brainpalace/config.yaml (or legacy path)
    """
    # 1. Environment variable override
    env_config = os.getenv("BRAINPALACE_CONFIG")
    if env_config:
        path = Path(env_config)
        if path.exists():
            logger.debug(f"Found config via BRAINPALACE_CONFIG: {path}")
            return path
        logger.warning(f"BRAINPALACE_CONFIG points to non-existent file: {env_config}")

    # 2. State directory (check both new and legacy env vars)
    state_dir = os.getenv("BRAINPALACE_STATE_DIR") or os.getenv("DOC_SERVE_STATE_DIR")
    if state_dir:
        state_config = Path(state_dir) / "config.yaml"
        if state_config.exists():
            logger.debug(f"Found config in state directory: {state_config}")
            return state_config

    # 3. Current directory
    cwd_config = Path.cwd() / "config.yaml"
    if cwd_config.exists():
        logger.debug(f"Found config in current directory: {cwd_config}")
        return cwd_config

    # 4. Walk up from CWD looking for .brainpalace/config.yaml (or legacy)
    current = Path.cwd()
    root = Path(current.anchor)
    while current != root:
        new_config = current / ".brainpalace" / "config.yaml"
        if new_config.exists():
            logger.debug(f"Found config walking up from CWD: {new_config}")
            return new_config
        legacy_config = current / ".claude" / "brainpalace" / "config.yaml"
        if legacy_config.exists():
            logger.debug(f"Found config walking up from CWD: {legacy_config}")
            return legacy_config
        current = current.parent

    return None


def _find_global_config_file() -> Path | None:
    """Find the GLOBAL (machine-wide) config file — the middle resolution layer.

    Search order (global layer of ``code < global < project``):
    5. XDG config ~/.config/brainpalace/config.yaml (preferred)
    6. Legacy ~/.brainpalace/config.yaml (deprecated, logs warning)
    """
    # 5. XDG config directory (checked before legacy per XDG standard)
    # Server cannot import from CLI package — inline the XDG logic
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        xdg_config_dir = Path(xdg_config_home) / "brainpalace"
    else:
        xdg_config_dir = Path.home() / ".config" / "brainpalace"

    xdg_config = xdg_config_dir / "config.yaml"
    if xdg_config.exists():
        logger.debug(f"Found config in XDG config directory: {xdg_config}")
        return xdg_config

    xdg_alt = xdg_config_dir / "brainpalace.yaml"
    if xdg_alt.exists():
        logger.debug(f"Found config in XDG config directory: {xdg_alt}")
        return xdg_alt

    # 6. Legacy path ~/.brainpalace/ (deprecated, fallback only)
    home_config = Path.home() / ".brainpalace" / "config.yaml"
    if home_config.exists():
        logger.warning(
            "Using legacy config path ~/.brainpalace/config.yaml. "
            "Run 'brainpalace start' to migrate to ~/.config/brainpalace/."
        )
        return home_config

    home_alt = Path.home() / ".brainpalace" / "brainpalace.yaml"
    if home_alt.exists():
        logger.warning(
            "Using legacy config path ~/.brainpalace/brainpalace.yaml. "
            "Run 'brainpalace start' to migrate to ~/.config/brainpalace/."
        )
        return home_alt

    return None


def _find_config_file() -> Path | None:
    """Backward-compatible single-file resolver: project first, else global.

    Prefer :func:`load_merged_config_dict` for new code — this returns only the
    single most-specific file and does NOT layer global under project.
    """
    return _find_project_config_file() or _find_global_config_file()


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``over`` onto ``base``; ``over`` wins per key.

    Nested dicts are merged key-by-key; any non-dict value (or a type change)
    replaces wholesale. Inputs are not mutated. This is the engine of the
    ``code < global < project`` precedence: call with ``base=global`` and
    ``over=project`` to let project values override global ones per key while
    inheriting every key the project omits.
    """
    out: dict[str, Any] = dict(base)
    for key, value in over.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_merged_config_dict(project_path: Path | None = None) -> dict[str, Any]:
    """Resolve the effective config dict by layering ``global < project``.

    Pydantic supplies the lowest (code-default) layer when these dicts are fed
    into a settings model, so the full precedence is ``code < global < project``.
    Environment-variable overrides are applied later, at point of use, so they
    remain the highest-precedence layer (``env > project > global > code``).

    Args:
        project_path: Explicit project config file; defaults to the resolved
            project-scoped file (``_find_project_config_file``).
    """
    global_file = _find_global_config_file()
    global_dict = _load_yaml_config(global_file) if global_file else {}

    proj_file = project_path or _find_project_config_file()
    # A project file that IS the global file (e.g. running from the XDG dir)
    # must not be merged onto itself.
    if proj_file and global_file and Path(proj_file).resolve() == global_file.resolve():
        proj_file = None
    project_dict = _load_yaml_config(proj_file) if proj_file else {}

    return _deep_merge(global_dict, project_dict)


def load_raw_config(config_path: Path | None = None) -> dict[str, Any]:
    """Raw effective config dict for per-block loaders (git/session/bm25/…).

    With an explicit ``config_path`` this reads that single file verbatim (used
    by tests and the server-less estimate). Otherwise it returns the merged
    ``global < project`` dict so every block loader inherits global values for
    keys the project omits, consistent with ``load_provider_settings``.
    """
    if config_path is not None:
        path = Path(config_path)
        return _load_yaml_config(path) if path.exists() else {}
    return load_merged_config_dict()


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load YAML configuration from file.

    Args:
        path: Path to YAML config file

    Returns:
        Configuration dictionary

    Raises:
        ConfigurationError: If YAML parsing fails
    """
    from brainpalace_server.providers.exceptions import ConfigurationError

    # Tolerate a directory (e.g. a caller handing us `state_dir` instead of the
    # config file): resolve to the conventional `config.yaml` inside it. A bare
    # `open(dir)` raises IsADirectoryError, which is easy to swallow and hard to
    # spot — see the doc_weight regression. `.exists()` guards upstream do NOT
    # catch this, since a directory also `.exists()`.
    path = Path(path)
    if path.is_dir():
        path = path / "config.yaml"

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
            return config if config else {}
    except yaml.YAMLError as e:
        raise ConfigurationError(
            f"Failed to parse config file {path}: {e}",
            "config",
        ) from e
    except OSError as e:
        raise ConfigurationError(
            f"Failed to read config file {path}: {e}",
            "config",
        ) from e


@lru_cache
def load_provider_settings() -> ProviderSettings:
    """Load provider settings from YAML config or defaults.

    This function:
    1. Searches for config.yaml in standard locations
    2. Parses YAML and validates against Pydantic models
    3. Falls back to defaults (OpenAI embeddings + Anthropic summarization)

    Returns:
        Validated ProviderSettings instance
    """
    # Resolve the effective config by layering global < project (code defaults
    # come from the pydantic model below). env vars still win at point of use.
    project_file = _find_project_config_file()
    global_file = _find_global_config_file()
    raw_config = load_merged_config_dict()

    if project_file or global_file:
        logger.info(
            "Loading provider config (project=%s, global=%s)",
            project_file,
            global_file,
        )
        if "graphrag" in raw_config:
            logger.info(
                "Parsed 'graphrag:' section — values are applied to GRAPH_* "
                "settings at server startup (env vars take precedence). See "
                "docs/PROVIDER_CONFIGURATION.md.",
            )
        settings = ProviderSettings(**raw_config)
    else:
        logger.info("No config file found, using default providers")
        settings = ProviderSettings()

    # Log active configuration
    logger.info(
        f"Active embedding provider: {settings.embedding.provider} "
        f"(model: {settings.embedding.model})"
    )
    logger.info(
        f"Active summarization provider: {settings.summarization.provider} "
        f"(model: {settings.summarization.model})"
    )
    logger.info(
        f"Active reranker provider: {settings.reranker.provider} "
        f"(model: {settings.reranker.model})"
    )
    logger.info(f"Active storage backend: {settings.storage.backend}")

    return settings


def clear_settings_cache() -> None:
    """Clear the cached provider settings (for testing)."""
    load_provider_settings.cache_clear()


def validate_provider_config(
    settings: ProviderSettings,
    reranking_enabled: bool = False,
) -> list[ValidationError]:
    """Validate provider configuration and return list of errors.

    Checks:
    - API keys are available for providers that need them (CRITICAL)
    - Reranker base_url is set for Ollama reranker when enabled (WARNING)

    Args:
        settings: Provider settings to validate
        reranking_enabled: Whether reranking is enabled (from app settings)

    Returns:
        List of ValidationError objects (empty if valid)
    """
    errors: list[ValidationError] = []

    # Validate embedding provider
    if settings.embedding.provider != EmbeddingProviderType.OLLAMA:
        api_key = settings.embedding.get_api_key()
        if not api_key:
            env_var = settings.embedding.resolved_api_key_env() or "OPENAI_API_KEY"
            errors.append(
                ValidationError(
                    message=(
                        f"Missing API key for {settings.embedding.provider} "
                        f"embeddings. Set {env_var} environment variable."
                    ),
                    severity=ValidationSeverity.CRITICAL,
                    provider_type="embedding",
                    field="api_key",
                )
            )

    # Validate summarization provider
    if settings.summarization.provider != SummarizationProviderType.OLLAMA:
        api_key = settings.summarization.get_api_key()
        if not api_key:
            env_var = (
                settings.summarization.resolved_api_key_env() or "ANTHROPIC_API_KEY"
            )
            errors.append(
                ValidationError(
                    message=(
                        f"Missing API key for {settings.summarization.provider} "
                        f"summarization. Set {env_var} environment variable."
                    ),
                    severity=ValidationSeverity.CRITICAL,
                    provider_type="summarization",
                    field="api_key",
                )
            )

    # Validate reranker provider (when reranking is enabled)
    if reranking_enabled:
        if settings.reranker.provider == RerankerProviderType.OLLAMA:
            base_url = settings.reranker.get_base_url()
            if not base_url:
                errors.append(
                    ValidationError(
                        message=(
                            "Ollama reranker enabled but no base_url configured. "
                            "Set reranker.base_url in config.yaml or use "
                            "default (http://localhost:11434)."
                        ),
                        severity=ValidationSeverity.WARNING,
                        provider_type="reranker",
                        field="base_url",
                    )
                )

    # Validate storage backend configuration
    if settings.storage.backend == "postgres":
        if not settings.storage.postgres:
            # Check if DATABASE_URL env var is set as an alternative
            if not os.getenv("DATABASE_URL"):
                errors.append(
                    ValidationError(
                        message=(
                            "PostgreSQL backend selected but no postgres "
                            "configuration provided. Set storage.postgres "
                            "in config.yaml with connection parameters "
                            "(host, port, database, user, password) or "
                            "set DATABASE_URL environment variable."
                        ),
                        severity=ValidationSeverity.WARNING,
                        provider_type="storage",
                        field="postgres",
                    )
                )
        elif "host" not in settings.storage.postgres:
            # postgres config exists but missing host key
            if not os.getenv("DATABASE_URL"):
                errors.append(
                    ValidationError(
                        message=(
                            "PostgreSQL configuration missing 'host' key. "
                            "Ensure storage.postgres.host is set in "
                            "config.yaml or set DATABASE_URL."
                        ),
                        severity=ValidationSeverity.WARNING,
                        provider_type="storage",
                        field="postgres.host",
                    )
                )

    return errors


def has_critical_errors(errors: list[ValidationError]) -> bool:
    """Check if any validation errors are critical.

    Args:
        errors: List of validation errors

    Returns:
        True if any error has CRITICAL severity
    """
    return any(e.severity == ValidationSeverity.CRITICAL for e in errors)

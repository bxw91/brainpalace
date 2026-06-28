"""Configuration loader for BrainPalace CLI.

Provides YAML-based configuration loading with multiple search paths,
allowing projects and users to configure BrainPalace without environment variables.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from pydantic import BaseModel, Field

from brainpalace_cli.discovery import discover_project_dir, discover_server_url
from brainpalace_cli.xdg_paths import get_xdg_config_dir, is_initialized_state_dir

logger = logging.getLogger(__name__)

# Default state directory name within project root
STATE_DIR_NAME = ".brainpalace"
LEGACY_STATE_DIR_NAME = ".claude/brainpalace"


class ServerNotReachableError(click.ClickException):
    """The current project's own server isn't reachable.

    Raised by :func:`get_server_url` when an *initialized* project owns the CWD
    but its recorded server can't be validated as live. We deliberately do NOT
    fall back to ``config.server.url`` / the default port in that case: that URL
    is global and frequently points at a *different* project's server (e.g.
    whatever is bound to ``:8000``), so a command would silently report another
    project's data. Failing loudly is correct — the fix for the wrong-server bug.
    """

    def __init__(self, project: Path) -> None:
        super().__init__(
            f"BrainPalace server for this project isn't reachable: {project}\n"
            "It may still be starting up, or it's stopped. "
            "Start it with: brainpalace start"
        )
        self.project = project


class ServerConfig(BaseModel):
    """Server-related configuration."""

    url: str = Field(
        default="http://127.0.0.1:8000",
        description="Server URL for CLI to connect to",
    )
    host: str = Field(
        default="127.0.0.1",
        description="Server bind host",
    )
    port: int = Field(
        default=8000,
        description="Server port (0 = auto-assign)",
    )
    auto_port: bool = Field(
        default=True,
        description="Automatically select available port if preferred port is in use",
    )


class EmbeddingConfig(BaseModel):
    """Embedding provider configuration."""

    provider: str = Field(
        default="openai",
        description="Embedding provider: openai, ollama, cohere",
    )
    model: str = Field(
        default="text-embedding-3-large",
        description="Model name for embeddings",
    )
    api_key: str | None = Field(
        default=None,
        description="API key (alternative to api_key_env)",
    )
    api_key_env: str | None = Field(
        default="OPENAI_API_KEY",
        description="Environment variable containing API key",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL (for Ollama or compatible APIs)",
    )


class SummarizationConfig(BaseModel):
    """Summarization provider configuration."""

    provider: str = Field(
        default="anthropic",
        description="Provider: anthropic, openai, ollama, gemini, grok",
    )
    model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Model name for summarization",
    )
    api_key: str | None = Field(
        default=None,
        description="API key (alternative to api_key_env)",
    )
    api_key_env: str | None = Field(
        default="ANTHROPIC_API_KEY",
        description="Environment variable containing API key",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom base URL",
    )


class BrainPalaceConfig(BaseModel):
    """Complete BrainPalace configuration."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    summarization: SummarizationConfig = Field(default_factory=SummarizationConfig)


def _find_config_file(start_path: Path | None = None) -> Path | None:
    """Find configuration file in standard locations.

    Search order:
    1. BRAINPALACE_CONFIG environment variable
    2. Current directory: brainpalace.yaml or config.yaml
    3. Project .brainpalace/config.yaml (or legacy .claude/brainpalace/)
    4. User home: ~/.brainpalace/config.yaml
    5. User home: ~/.config/brainpalace/config.yaml (XDG)

    Args:
        start_path: Starting directory for project search. Defaults to cwd.

    Returns:
        Path to config file or None if not found.
    """
    # 1. Environment variable override
    env_config = os.getenv("BRAINPALACE_CONFIG")
    if env_config:
        path = Path(env_config).expanduser()
        if path.exists():
            logger.debug(f"Using config from BRAINPALACE_CONFIG: {path}")
            return path
        logger.warning(f"BRAINPALACE_CONFIG points to non-existent file: {env_config}")

    start = (start_path or Path.cwd()).resolve()

    # 2. Current directory
    for name in ("brainpalace.yaml", "brainpalace.yml", "config.yaml"):
        cwd_config = start / name
        if cwd_config.exists():
            logger.debug(f"Using config from current directory: {cwd_config}")
            return cwd_config

    # 3. Project .brainpalace directory (or legacy .claude/brainpalace)
    # Walk up looking for state directory
    current = start
    while current != current.parent:
        new_config = current / ".brainpalace" / "config.yaml"
        if new_config.exists():
            logger.debug(f"Using config from project: {new_config}")
            return new_config
        legacy_config = current / ".claude" / "brainpalace" / "config.yaml"
        if legacy_config.exists():
            logger.debug(f"Using config from project: {legacy_config}")
            return legacy_config
        current = current.parent

    # 4. XDG config (checked before legacy per XDG standard)
    xdg_config_path = get_xdg_config_dir() / "config.yaml"
    if xdg_config_path.exists():
        logger.debug(f"Using config from XDG: {xdg_config_path}")
        return xdg_config_path

    # Also check brainpalace.yaml in XDG dir
    xdg_alt = get_xdg_config_dir() / "brainpalace.yaml"
    if xdg_alt.exists():
        logger.debug(f"Using config from XDG: {xdg_alt}")
        return xdg_alt

    # 5. Legacy path ~/.brainpalace/ (deprecated, fallback only)
    home = Path.home()
    home_config = home / ".brainpalace" / "config.yaml"
    if home_config.exists():
        logger.debug(f"Using config from legacy home: {home_config}")
        sys.stderr.write(
            "Warning: Using legacy config path ~/.brainpalace/config.yaml. "
            "Run 'brainpalace start' to migrate to ~/.config/brainpalace/.\n"
        )
        return home_config

    home_alt = home / ".brainpalace" / "brainpalace.yaml"
    if home_alt.exists():
        logger.debug(f"Using config from legacy home: {home_alt}")
        sys.stderr.write(
            "Warning: Using legacy config path ~/.brainpalace/brainpalace.yaml. "
            "Run 'brainpalace start' to migrate to ~/.config/brainpalace/.\n"
        )
        return home_alt

    return None


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load YAML configuration from file.

    Args:
        path: Path to YAML config file.

    Returns:
        Configuration dictionary.

    Raises:
        ValueError: If YAML parsing fails.
    """
    try:
        with open(path) as f:
            config = yaml.safe_load(f)
            return config if config else {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse config file {path}: {e}") from e
    except OSError as e:
        raise ValueError(f"Failed to read config file {path}: {e}") from e


def load_config(start_path: Path | None = None) -> BrainPalaceConfig:
    """Load BrainPalace configuration.

    Searches for config file in standard locations and returns
    validated configuration. Falls back to defaults if no config found.

    Args:
        start_path: Starting directory for config search.

    Returns:
        Validated BrainPalaceConfig instance.
    """
    config_path = _find_config_file(start_path)

    if config_path:
        logger.info(f"Loading config from {config_path}")
        raw_config = _load_yaml_config(config_path)
        config = BrainPalaceConfig(**raw_config)
    else:
        logger.debug("No config file found, using defaults")
        config = BrainPalaceConfig()

    # Override with environment variables (highest precedence)
    if os.getenv("BRAINPALACE_URL"):
        config.server.url = os.getenv("BRAINPALACE_URL")  # type: ignore[assignment]

    return config


def _find_project_root(start_path: Path | None = None) -> Path:
    """Find the project root by looking for markers.

    Walks up from start_path looking for:
    1. Git repository root
    2. .claude/ directory
    3. pyproject.toml file

    Args:
        start_path: Starting directory. Defaults to cwd.

    Returns:
        Project root path or start_path if no markers found.
    """
    import subprocess

    start = (start_path or Path.cwd()).resolve()

    # Try git root first
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(start),
        )
        if result.returncode == 0:
            return Path(result.stdout.strip()).resolve()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Walk up looking for markers
    current = start
    while current != current.parent:
        if (current / ".brainpalace").is_dir():
            return current
        if (current / ".claude").is_dir():
            return current
        if (current / "pyproject.toml").is_file():
            return current
        current = current.parent

    return start


#: Stable identifiers for *why* a project root was selected, surfaced by
#: ``brainpalace doctor`` so users on monorepos understand the resolution.
_RESOLVE_STRATEGY_LABELS = {
    "brainpalace_dir": f"found {STATE_DIR_NAME}/ in this dir or an ancestor",
    "legacy_claude_dir": f"found legacy {LEGACY_STATE_DIR_NAME}/",
    "git_root": "git repository root (no state dir present yet)",
    "claude_dir": ".claude/ marker in this dir or an ancestor",
    "pyproject": "pyproject.toml marker in this dir or an ancestor",
    "cwd_fallback": "no markers found — falling back to cwd",
}


def resolve_project_root_with_strategy(
    start_path: Path | None = None,
) -> tuple[Path, str]:
    """Resolve the project root and report which rule matched.

    Returns ``(root, strategy_label)`` where ``strategy_label`` is a stable
    key into :data:`_RESOLVE_STRATEGY_LABELS`. The state dir is checked
    *before* the git root so nested projects in a monorepo resolve to the
    nearest ``.brainpalace/`` rather than the repository top-level.
    """
    import subprocess

    start = (start_path or Path.cwd()).resolve()

    # 1. Nearest *initialized* .brainpalace/ (or legacy .claude/brainpalace/)
    #    ancestor. A bare scaffold (no config.yaml / runtime.json) is skipped so
    #    a stray dir in a monorepo sub-package does not shadow the real root.
    current = start
    while True:
        state_dir = current / STATE_DIR_NAME
        if state_dir.is_dir() and is_initialized_state_dir(state_dir):
            return current, "brainpalace_dir"
        legacy_dir = current / LEGACY_STATE_DIR_NAME
        if legacy_dir.is_dir() and is_initialized_state_dir(legacy_dir):
            return current, "legacy_claude_dir"
        if current == current.parent:
            break
        current = current.parent

    # 2. Git repository root.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(start),
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve(), "git_root"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # 3. Other markers walking up.
    current = start
    while True:
        if (current / ".claude").is_dir():
            return current, "claude_dir"
        if (current / "pyproject.toml").is_file():
            return current, "pyproject"
        if current == current.parent:
            break
        current = current.parent

    # 4. Nothing matched.
    return start, "cwd_fallback"


def resolve_project_root(start_path: Path | None = None) -> Path:
    """Resolve the project root (without the strategy label)."""
    root, _ = resolve_project_root_with_strategy(start_path)
    return root


def get_state_dir(
    config: BrainPalaceConfig | None = None,
    project_root: Path | None = None,
) -> Path:
    """Get the resolved state directory path.

    Resolution order:
    1. Detect project root and check for .brainpalace/ (or legacy .claude/brainpalace/)
    2. BRAINPALACE_STATE_DIR environment variable (explicit override)
    3. Default: {project_root}/.brainpalace

    A custom state-dir location is set ONLY via BRAINPALACE_STATE_DIR — it can't
    be a config key, because the project config lives INSIDE the state dir.

    Args:
        config: Optional pre-loaded config.
        project_root: Project root for default path.

    Returns:
        Resolved state directory path.
    """
    # 1. Auto-detect project root and check for existing state dir
    if project_root is None:
        project_root = _find_project_root()

    # Check new path first, then legacy
    new_state_dir = project_root / STATE_DIR_NAME
    if new_state_dir.exists() and is_initialized_state_dir(new_state_dir):
        return new_state_dir

    legacy_state_dir = project_root / LEGACY_STATE_DIR_NAME
    if legacy_state_dir.exists() and is_initialized_state_dir(legacy_state_dir):
        return legacy_state_dir

    # 2. Environment variable as explicit override (the only custom-location knob)
    env_state_dir = os.getenv("BRAINPALACE_STATE_DIR")
    if env_state_dir:
        return Path(env_state_dir).expanduser().resolve()

    # 3. Default: project_root/.brainpalace
    return project_root / STATE_DIR_NAME


def get_server_url(
    config: BrainPalaceConfig | None = None, *, raise_on_unreachable: bool = True
) -> str:
    """Get the server URL.

    Resolution order:
    1. BRAINPALACE_URL environment variable
    2. CWD-based discovery: the running server that owns the current project.
       Walks up from the current directory to ``.brainpalace/`` and validates
       the server is live — see
       :func:`brainpalace_cli.discovery.discover_server_url`. This correctly
       handles mono-repos, where the git root is not the project root.
    3. If an initialized project owns the CWD but no live server validates,
       raise :class:`ServerNotReachableError` instead of falling through — never
       silently target an unrelated server (the global default frequently points
       at a *different* project's server).
    4. config.server.url from the config file (only when no owning project)
    5. Default: http://127.0.0.1:8000

    Args:
        config: Optional pre-loaded config.
        raise_on_unreachable: When True (default), raise if an owning project is
            found but no live server validates. Pass False for diagnostics
            (``doctor``) that must still compute a would-be URL for a down server.

    Returns:
        Server URL string.

    Raises:
        ServerNotReachableError: An owning project was found but its server is
            not reachable (only when ``raise_on_unreachable`` is True).
    """
    # Environment variable takes precedence (explicit override wins)
    env_url = os.getenv("BRAINPALACE_URL")
    if env_url:
        return env_url

    # CWD-based discovery of the live server for the current project (B1)
    discovered = discover_server_url()
    if discovered:
        return discovered

    # No live owning server. If an initialized project still owns the CWD, the
    # global config/default URL would point somewhere else entirely (commonly a
    # different project's server on :8000), so a command would report the wrong
    # project's data. Fail loudly rather than guess. (Fix for the wrong-server
    # bug — affects every command that resolves a URL this way.)
    project = discover_project_dir()
    if project is not None and raise_on_unreachable:
        raise ServerNotReachableError(project)

    # No owning project (or caller opted out, e.g. `doctor` which must still
    # report a would-be URL for a down server) — use the configured/default URL.
    if config is None:
        config = load_config()

    return config.server.url

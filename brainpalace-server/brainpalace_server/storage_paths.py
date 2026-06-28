"""State directory and storage path resolution."""

import os
from pathlib import Path

STATE_DIR_NAME = ".brainpalace"
LEGACY_STATE_DIR_NAME = ".claude/brainpalace"

SUBDIRECTORIES = [
    "data",
    "data/chroma_db",
    "data/bm25_index",
    "data/llamaindex",
    "data/graph_index",
    "logs",
    "manifests",
    "embedding_cache",  # Phase 16: persistent embedding cache
    "db",  # durable SQLite stores (query_log/usage_metrics/records/extraction_pending)
    "state",  # small durable cursors/markers + append-only audit-event jsonl
]

# Subfolder names for the grouped layout. The state-dir root keeps only the
# user-facing/discovery files (config.yaml, runtime.json, pid/lock, server.log);
# everything else lives under a named group.
DB_SUBDIR = "db"
STATE_SUBDIR = "state"


def db_path(state_dir: Path, name: str) -> Path:
    """Resolve ``<state_dir>/db/<name>``, creating the ``db/`` dir."""
    d = Path(state_dir) / DB_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def state_file_path(state_dir: Path, name: str) -> Path:
    """Resolve ``<state_dir>/state/<name>``, creating the ``state/`` dir."""
    d = Path(state_dir) / STATE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def resolve_state_dir(project_root: Path) -> Path:
    """Resolve the state directory for a project.

    Checks for `.brainpalace/` first, then falls back to the legacy
    `.claude/brainpalace/` path for backward compatibility. If neither
    exists, returns the new `.brainpalace/` path.

    Args:
        project_root: Resolved project root path.

    Returns:
        Path to the state directory.
    """
    resolved = project_root.resolve()
    new_dir = resolved / STATE_DIR_NAME
    if new_dir.is_dir():
        return new_dir

    legacy_dir = resolved / LEGACY_STATE_DIR_NAME
    if legacy_dir.is_dir():
        return legacy_dir

    return new_dir


def resolve_storage_paths(state_dir: Path) -> dict[str, Path]:
    """Resolve all storage paths relative to state directory.

    Creates directories if they don't exist.

    Args:
        state_dir: Path to the state directory.

    Returns:
        Dictionary mapping storage names to paths.
    """
    paths: dict[str, Path] = {
        "state_dir": state_dir,
        "data": state_dir / "data",
        "chroma_db": state_dir / "data" / "chroma_db",
        "bm25_index": state_dir / "data" / "bm25_index",
        "llamaindex": state_dir / "data" / "llamaindex",
        "graph_index": state_dir / "data" / "graph_index",
        "logs": state_dir / "logs",
        "manifests": state_dir / "manifests",
        "embedding_cache": state_dir / "embedding_cache",  # Phase 16
        "db": state_dir / DB_SUBDIR,
        "state": state_dir / STATE_SUBDIR,
    }

    # Create directories
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    return paths


def resolve_shared_project_dir(project_id: str) -> Path:
    """Resolve per-project storage under shared daemon.

    Checks BRAINPALACE_SHARED_DIR env var first, then XDG_DATA_HOME/brainpalace,
    falling back to ~/.local/share/brainpalace.

    Args:
        project_id: Unique project identifier.

    Returns:
        Path to shared project data directory.
    """
    base_env = os.environ.get("BRAINPALACE_SHARED_DIR")
    if base_env:
        shared_dir = Path(base_env) / "projects" / project_id / "data"
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            shared_dir = (
                Path(xdg_data_home) / "brainpalace" / "projects" / project_id / "data"
            )
        else:
            shared_dir = (
                Path.home()
                / ".local"
                / "share"
                / "brainpalace"
                / "projects"
                / project_id
                / "data"
            )
    shared_dir.mkdir(parents=True, exist_ok=True)
    return shared_dir

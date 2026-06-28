"""XDG Base Directory path resolution and legacy migration helpers.

This module is the single source of truth for all XDG directory resolution
in the BrainPalace CLI. Every other module should import from here.

XDG Base Directory specification:
  Config: $XDG_CONFIG_HOME/brainpalace  (default: ~/.config/brainpalace)
  State:  $XDG_STATE_HOME/brainpalace   (default: ~/.local/state/brainpalace)
  Data:   $XDG_DATA_HOME/brainpalace    (default: ~/.local/share/brainpalace)

Legacy path: ~/.brainpalace (pre-XDG, deprecated)
"""

import logging
import os
import shutil
from pathlib import Path

import click

logger = logging.getLogger(__name__)

# Legacy directory — deprecated, replaced by XDG paths
LEGACY_DIR: Path = Path.home() / ".brainpalace"


def is_initialized_state_dir(state_dir: Path) -> bool:
    """True if a ``.brainpalace/`` (or legacy) dir is an initialized project.

    A directory counts as a real project root only when it holds one of the
    initialized markers: ``config.yaml`` (the canonical marker — ``brainpalace
    init`` writes it), ``runtime.json`` (written by a running server), or the
    legacy ``config.json`` (retired, but still detected so old projects resolve).
    A bare scaffold (only ``data/`` dirs, created as a side effect) has none of
    these and returns ``False`` so discovery walks past it to the true project /
    git root.

    Lives here, the lowest-level module, so both ``config`` and ``discovery``
    can import it without an import cycle.
    """
    return (
        (state_dir / "config.yaml").is_file()
        or (state_dir / "config.json").is_file()
        or (state_dir / "runtime.json").is_file()
    )


def get_xdg_config_dir() -> Path:
    """Return XDG config directory for BrainPalace.

    Returns:
        $XDG_CONFIG_HOME/brainpalace if XDG_CONFIG_HOME is set,
        otherwise ~/.config/brainpalace.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "brainpalace"
    return Path.home() / ".config" / "brainpalace"


def get_xdg_state_dir() -> Path:
    """Return XDG state directory for BrainPalace.

    Returns:
        $XDG_STATE_HOME/brainpalace if XDG_STATE_HOME is set,
        otherwise ~/.local/state/brainpalace.
    """
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "brainpalace"
    return Path.home() / ".local" / "state" / "brainpalace"


def get_registry_path() -> Path:
    """Return path to the global registry.json file.

    Prefers XDG state dir over legacy path. Falls back to legacy if
    registry.json exists only there. Returns XDG path as default write
    target when neither exists.

    Returns:
        Path to registry.json (may not exist yet).
    """
    xdg_registry = get_xdg_state_dir() / "registry.json"
    if xdg_registry.exists():
        return xdg_registry

    # Legacy fallback — use Path.home() dynamically so tests can mock it
    legacy_registry = Path.home() / ".brainpalace" / "registry.json"
    if legacy_registry.exists():
        return legacy_registry

    # Default write target: XDG state dir
    return xdg_registry


def migrate_legacy_paths(*, silent: bool = False) -> bool:
    """Migrate ~/.brainpalace to XDG directories.

    Copies config.yaml to XDG config dir and registry.json to XDG state
    dir, then removes the legacy ~/.brainpalace directory.

    This migration is non-blocking — errors are caught and logged.
    Migration is skipped if either XDG directory already exists (idempotent).

    Args:
        silent: If True, suppress output to stderr.

    Returns:
        True if migration succeeded, False otherwise.
    """
    # Use Path.home() dynamically so tests can mock it
    legacy_dir = Path.home() / ".brainpalace"

    # Skip if legacy dir doesn't exist
    if not legacy_dir.exists():
        return False

    xdg_config = get_xdg_config_dir()
    xdg_state = get_xdg_state_dir()

    # Skip if either XDG dir already exists (already migrated)
    if xdg_config.exists() or xdg_state.exists():
        return False

    try:
        # Create XDG directories
        xdg_config.mkdir(parents=True, exist_ok=True)
        xdg_state.mkdir(parents=True, exist_ok=True)

        # Copy config files to XDG config dir
        for config_name in ("config.yaml", "brainpalace.yaml"):
            src = legacy_dir / config_name
            if src.exists():
                shutil.copy2(src, xdg_config / config_name)

        # Copy state files to XDG state dir
        for state_name in ("registry.json",):
            src = legacy_dir / state_name
            if src.exists():
                shutil.copy2(src, xdg_state / state_name)

        # Remove legacy directory
        shutil.rmtree(legacy_dir)

        if not silent:
            click.echo(
                f"Migrated BrainPalace config from {legacy_dir} to XDG directories:\n"
                f"  Config: {xdg_config}\n"
                f"  State:  {xdg_state}",
                err=True,
            )

        return True

    except (PermissionError, OSError) as e:
        logger.warning("Failed to migrate legacy BrainPalace config: %s", e)
        if not silent:
            click.echo(
                f"Warning: Could not migrate {legacy_dir} to XDG directories: {e}",
                err=True,
            )
        return False

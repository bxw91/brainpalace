"""Per-key config resolution across ``project < global < code`` (CLI side).

Mirrors the server's read-time merge (``load_merged_config_dict``) for CLI
surfaces — ``config show``/``config unset`` and ``init`` prompt defaults. For any
dotted key it answers: the effective value, which layer supplied it, and what it
WOULD fall back to if the project value were unset.

Project config is SPARSE: it stores only values that diverge from what would be
inherited. A key absent from the project file is intentionally inherited from the
global config, and absent from that too, from the code default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .xdg_paths import get_xdg_config_dir

_MISSING = object()

#: Code-level defaults for the keys CLI surfaces resolve/display. These mirror
#: the server pydantic defaults; kept here (not imported) so the CLI need not
#: construct server settings just to show a fallback value.
CODE_DEFAULTS: dict[str, Any] = {
    "embedding.provider": "openai",
    "embedding.model": "text-embedding-3-large",
    "summarization.provider": "anthropic",
    "summarization.model": "claude-haiku-4-5-20251001",
    "reranker.enabled": False,
    "graphrag.enabled": True,
    "graphrag.store_type": "sqlite",
    "graphrag.use_code_metadata": True,
    "bm25.language": "en",
    "bm25.engine": "stem",
    "git_indexing.enabled": False,
    "git_indexing.depth": 0,
    "session_indexing.enabled": False,
    "session_indexing.archive.enabled": True,
    "session_extraction.mode": "subagent",
}


def global_config_path() -> Path:
    """Path to the global (machine-wide XDG) ``config.yaml``."""
    return get_xdg_config_dir() / "config.yaml"


def read_yaml(path: Path | None) -> dict[str, Any]:
    """Load a YAML config file to a dict; empty/missing/invalid → ``{}``."""
    if path is None or not Path(path).exists():
        return {}
    try:
        data = yaml.safe_load(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _get(config: dict[str, Any], dotpath: str) -> Any:
    cur: Any = config
    for part in dotpath.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def resolve(
    dotpath: str,
    project_config: dict[str, Any],
    global_config: dict[str, Any],
) -> tuple[Any, str]:
    """Resolve ``dotpath`` across project < global < code.

    Returns ``(value, source)`` where source is
    ``"project" | "global" | "code" | "unset"``.
    """
    pv = _get(project_config, dotpath)
    if pv is not _MISSING:
        return pv, "project"
    gv = _get(global_config, dotpath)
    if gv is not _MISSING:
        return gv, "global"
    if dotpath in CODE_DEFAULTS:
        return CODE_DEFAULTS[dotpath], "code"
    return None, "unset"


def inherited(
    dotpath: str,
    global_config: dict[str, Any],
) -> tuple[Any, str]:
    """What ``dotpath`` would resolve to if the project value were unset.

    Used both for the dashboard "if you unset, you'll get X from <source>" hint
    and for init's "answer equals inherited → don't write (inherit)" rule.
    """
    gv = _get(global_config, dotpath)
    if gv is not _MISSING:
        return gv, "global"
    if dotpath in CODE_DEFAULTS:
        return CODE_DEFAULTS[dotpath], "code"
    return None, "unset"


def unset_dotpath(config: dict[str, Any], dotpath: str) -> bool:
    """Delete ``dotpath`` from ``config`` in place, pruning emptied parents.

    Returns True if a key was removed. Mutates ``config``.
    """
    parts = dotpath.split(".")
    stack: list[tuple[dict[str, Any], str]] = []
    cur: Any = config
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return False
        stack.append((cur, part))
        cur = cur[part]
    leaf = parts[-1]
    if not isinstance(cur, dict) or leaf not in cur:
        return False
    del cur[leaf]
    # Prune now-empty parent dicts (don't leave `bm25: {}` behind).
    for parent, key in reversed(stack):
        if parent[key] == {}:
            del parent[key]
        else:
            break
    return True

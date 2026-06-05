"""Nested-gitignore evaluator with full Git semantics.

Builds a per-directory cache of `pathspec.PathSpec` objects from every
`.gitignore` file under a project root. `is_ignored(path)` walks the
directory chain from the path up to the project root, applying each
gitignore's patterns. The nearest gitignore's rules win on conflict —
including negation rules (`!foo`) — matching Git's behaviour.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pathspec

logger = logging.getLogger(__name__)


class GitignoreMatcher:
    """Per-project `.gitignore` matcher with nested + negation support.

    Construct once per project_root via :py:meth:`from_project_root`. The
    matcher walks the tree at construction time, builds a `PathSpec` per
    directory containing a `.gitignore`, and caches them. `is_ignored()` is
    O(depth) per call.
    """

    def __init__(
        self,
        project_root: Path,
        specs_by_dir: dict[Path, pathspec.PathSpec],
        root_specs: list[pathspec.PathSpec] | None = None,
    ) -> None:
        self._project_root = project_root.resolve()
        self._specs_by_dir = specs_by_dir
        self._root_specs = root_specs or []

    @classmethod
    def from_project_root(cls, project_root: Path) -> GitignoreMatcher:
        """Scan project_root for `.gitignore` files and build the matcher."""
        root = project_root.resolve()
        specs: dict[Path, pathspec.PathSpec] = {}
        for gitignore in root.rglob(".gitignore"):
            if not gitignore.is_file():
                continue
            try:
                lines = gitignore.read_text(errors="replace").splitlines()
            except OSError as exc:
                logger.warning(f"Failed to read {gitignore}: {exc}")
                continue
            spec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
            specs[gitignore.parent.resolve()] = spec
        root_specs = _load_root_level_specs(root)
        return cls(root, specs, root_specs)

    def is_ignored(self, path: Path) -> bool:
        """Return True if `path` is ignored by any applicable `.gitignore`.

        Walks the chain from `path`'s parent up to `project_root`. For each
        directory containing a `.gitignore`, evaluates the path RELATIVE to
        that directory. The nearest matching rule (whether ignore or
        negation) wins — Git semantics.
        """
        target = path.resolve()
        try:
            target.relative_to(self._project_root)
        except ValueError:
            return False  # outside project root

        # Walk from project_root downward; nearest gitignore's verdict wins.
        verdict: bool | None = None

        # Lowest precedence: global core.excludesFile + $GIT_DIR/info/exclude,
        # matched relative to the project root (like a root-level .gitignore).
        # Any .gitignore in the tree below overrides these.
        if self._root_specs:
            rel_root = target.relative_to(self._project_root).as_posix()
            if target.is_dir():
                rel_root += "/"
            for spec in self._root_specs:
                if spec.match_file(rel_root):
                    verdict = True
                elif _is_explicitly_negated(spec, rel_root):
                    verdict = False

        chain: list[Path] = []
        cur = target.parent
        while True:
            chain.append(cur)
            if cur == self._project_root:
                break
            if cur.parent == cur:
                break
            cur = cur.parent

        # Outer dirs first so inner gitignore overrides.
        for d in reversed(chain):
            dir_spec = self._specs_by_dir.get(d)
            if dir_spec is None:
                continue
            try:
                rel = target.relative_to(d).as_posix()
            except ValueError:
                continue
            if target.is_dir():
                rel += "/"
            if dir_spec.match_file(rel):
                verdict = True
            else:
                # pathspec.match_file returns True only when a positive rule
                # matches; a negation rule produces False. We need to detect
                # "explicitly un-ignored" to override an ancestor. pathspec
                # doesn't expose that directly, so re-check with the file's
                # negation pattern via the public check_file_negated API.
                negated = _is_explicitly_negated(dir_spec, rel)
                if negated:
                    verdict = False

        return bool(verdict) if verdict is not None else False


def _is_explicitly_negated(spec: pathspec.PathSpec, rel: str) -> bool:
    """Return True if `rel` matches a negation pattern in `spec`.

    `pathspec.PathSpec.match_file()` collapses negations into a single
    bool; for nested-gitignore precedence we need to know whether a child
    gitignore explicitly UN-ignored a path so we can override an ancestor's
    ignore rule.
    """
    for pattern in spec.patterns:
        if getattr(pattern, "include", None) is False:
            if pattern.match_file(rel):
                return True
    return False


def _git_common_dir(root: Path) -> Path | None:
    """Resolve the common .git directory for `root`, or None if not a repo.

    Uses ``--git-common-dir`` (not ``--absolute-git-dir``) so that linked
    worktrees resolve to the shared git dir where ``info/exclude`` actually
    lives. The result can be relative; resolve it against `root`.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    raw = out.stdout.strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (root / p).resolve()
    return p if p.is_dir() else None


def _global_excludes_path(root: Path) -> Path | None:
    """Resolve git's global core.excludesFile (configured value or XDG default)."""
    configured = ""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "config", "--get", "core.excludesFile"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            configured = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        configured = ""
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    default = Path(xdg) / "git" / "ignore"
    return default if default.is_file() else None


def _spec_from_file(path: Path | None) -> pathspec.PathSpec | None:
    if path is None or not path.is_file():
        return None
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError as exc:
        logger.warning(f"Failed to read {path}: {exc}")
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _load_root_level_specs(root: Path) -> list[pathspec.PathSpec]:
    """Lowest-precedence ignore specs: global core.excludesFile, then
    $GIT_DIR/info/exclude. Returned lowest-precedence first, so the global
    file is overridable by info/exclude, and both by any .gitignore.
    """
    specs: list[pathspec.PathSpec] = []
    gx = _spec_from_file(_global_excludes_path(root))
    if gx is not None:
        specs.append(gx)
    gd = _git_common_dir(root)
    if gd is not None:
        ie = _spec_from_file(gd / "info" / "exclude")
        if ie is not None:
            specs.append(ie)
    return specs

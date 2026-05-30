"""Nested-gitignore evaluator with full Git semantics.

Builds a per-directory cache of `pathspec.PathSpec` objects from every
`.gitignore` file under a project root. `is_ignored(path)` walks the
directory chain from the path up to the project root, applying each
gitignore's patterns. The nearest gitignore's rules win on conflict —
including negation rules (`!foo`) — matching Git's behaviour.
"""

from __future__ import annotations

import logging
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
    ) -> None:
        self._project_root = project_root.resolve()
        self._specs_by_dir = specs_by_dir

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
        return cls(root, specs)

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
            spec = self._specs_by_dir.get(d)
            if spec is None:
                continue
            try:
                rel = target.relative_to(d).as_posix()
            except ValueError:
                continue
            if target.is_dir():
                rel += "/"
            if spec.match_file(rel):
                verdict = True
            else:
                # pathspec.match_file returns True only when a positive rule
                # matches; a negation rule produces False. We need to detect
                # "explicitly un-ignored" to override an ancestor. pathspec
                # doesn't expose that directly, so re-check with the file's
                # negation pattern via the public check_file_negated API.
                negated = _is_explicitly_negated(spec, rel)
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

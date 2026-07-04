"""Resolve Python import statements to repo files (§2b — exact, never guessed).

Maps a dotted or relative import to a real file on disk, searching from the
importing file's own directory upward (nearest-ancestor-first, a conservative
subset of Python's package resolution). A hit yields a file→file `imports`
edge; a miss on an absolute import stays an external `Module`; a miss on a
relative import yields nothing (it is intra-repo by construction — emitting an
external node for it would be a wrong edge).
"""

from __future__ import annotations

import os


def _candidates(base: str, dotted: str, names: list[str]) -> list[str]:
    """Candidate paths for `import dotted` / `from dotted import names`."""
    mod_path = dotted.replace(".", "/") if dotted else ""
    rels: list[str] = []
    for name in names:  # from X import name — name may be a submodule file
        prefix = f"{mod_path}/" if mod_path else ""
        rels.append(f"{prefix}{name}.py")
        rels.append(f"{prefix}{name}/__init__.py")
    if mod_path:
        rels.append(f"{mod_path}.py")
        rels.append(f"{mod_path}/__init__.py")
    return [os.path.join(base, r) for r in rels]


def resolve_import(
    importing_file: str,
    module: str,
    level: int = 0,
    names: list[str] | None = None,
    root: str | None = None,
) -> list[str]:
    """Repo file paths this import lands on (POSIX, deduped); [] if none."""
    importing_file = importing_file.replace("\\", "/")
    file_dir = os.path.dirname(importing_file)
    names = names or []

    if level > 0:  # relative import: exactly one anchored base
        base = file_dir
        for _ in range(level - 1):
            base = os.path.dirname(base)
        bases = [base]
    else:  # absolute: nearest ancestor wins, bounded by root when given
        bases = []
        root_norm = (root or "").replace("\\", "/").rstrip("/")
        cur = file_dir
        while cur:
            bases.append(cur)
            if root_norm and cur == root_norm:
                break
            nxt = os.path.dirname(cur)
            if nxt == cur:
                break
            cur = nxt

    hits: list[str] = []
    for base in bases:
        for cand in _candidates(base, module, names):
            cand = cand.replace("\\", "/")
            if cand != importing_file and os.path.isfile(cand):
                hits.append(cand)
        if hits:
            break  # nearest ancestor wins
    seen: set[str] = set()
    deduped: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    return deduped

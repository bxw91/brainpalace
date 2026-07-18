"""Bash search-command analysis for the PreToolUse search guard.

Ported from the BrainPalace repo's dev analyzer (project-scope
``.claude/hooks/search_guard_analyze.py``) per
``.planning/specs/2026-07-18-bash-search-guard-port.md``. Library API only —
the hook calls :func:`analyze_bash_command` directly; no stdin/stdout protocol.

Deliberate divergences from the dev analyzer (spec D2/D4):

- Manifest missing/empty -> ``target_indexed=False`` (the shipped guard fails
  open toward ALLOWING; the dev hook's enforce-inside-root fallback is a
  dev-repo choice we do not ship).
- No ``build_scope``/``--file-paths`` port — no consumer until phase 2
  (enforce-with-inline-answer).
- New ``pure_search`` field: enforce-mode may only DENY a call that is purely a
  search (the search segment plus at most read-only stdin filters), because a
  deny blocks the ENTIRE Bash command including any non-search segments.
- Relative operands resolve against the session ``cwd`` from the hook payload,
  not the project root.
"""

from __future__ import annotations

import glob as _glob
import json
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Commands that only filter/paginate their stdin. A search piped through these
#: is still "purely a search" for enforce-deny purposes (spec D4). Deliberately
#: excludes sed/awk/xargs/tee (all can write or execute).
_READONLY_FILTERS = frozenset({"head", "tail", "wc", "sort", "uniq", "cut", "less"})

_OPERATORS = {";", "|", "||", "&&", "&", "\n"}
_REDIR = re.compile(r"^\d*[<>]")  # a redirection token (optionally fd-prefixed)


@dataclass(frozen=True)
class BashSearchAnalysis:
    """Result of analyzing one Bash command string."""

    is_search: bool = False
    term: str = ""
    classify: str = "bm25"  # "bm25" | "grep" | "multi"
    target_indexed: bool = False
    pure_search: bool = False


def classify(pattern: str) -> str:
    """Classify a pattern by regex CONSTRUCT, not "has metacharacters".

    A character-class shorthand, bracket expression, quantifier, or anchor is a
    regex feature the BM25 ``\\w+`` tokenizer cannot honor (metachars vanish as
    delimiters; letters inside them survive as phantom tokens) -> grep is
    authoritative. Alternation (``foo\\|bar``) and escaped literals are faithful
    in BM25 and stay routed to bm25.
    """
    if not pattern:
        return "bm25"
    if re.search(r"\\[wWdDsS]", pattern):  # \w \d \s \W \D \S
        return "grep"
    if re.search(r"(?<!\\)\[", pattern):  # [...] bracket expression
        return "grep"
    if re.search(r"(?<!\\)[+*?]", pattern):  # unescaped quantifier
        return "grep"
    if re.search(r"(?<!\\)\{[0-9]*,?[0-9]*\}", pattern):  # {n,m} quantifier
        return "grep"
    if re.search(r"(?<!\\)[\^$]", pattern):  # unescaped anchor
        return "grep"
    return "bm25"


def _tokenize_line(line: str) -> list[str]:
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except Exception:
        return line.split()


def tokenize(cmdline: str) -> list[str]:
    """Tokenize with shell metacharacters (``;|&<>``) as their own tokens.

    Literal newlines don't survive punctuation-mode shlex as tokens (they are
    plain whitespace), so each physical line is tokenized separately and a
    ``"\\n"`` sentinel spliced between them for segmentation to split on.
    """
    toks: list[str] = []
    lines = (cmdline or "").split("\n")
    for idx, line in enumerate(lines):
        toks.extend(_tokenize_line(line))
        if idx != len(lines) - 1:
            toks.append("\n")
    return toks


def split_segments(toks: list[str]) -> list[list[str]]:
    """Split a token stream into shell-command segments on ``;|&&||&`` and newline."""
    segments: list[list[str]] = []
    current: list[str] = []
    for t in toks:
        if t in _OPERATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(t)
    if current:
        segments.append(current)
    return segments


def strip_redirections(seg: list[str]) -> list[str]:
    """Drop a redirection token and the operand it targets.

    Under punctuation-mode shlex a redirection is ALWAYS split from its target
    (``2>/dev/null`` -> "2", ">", "/dev/null"), so eating the token right after
    any redirection match is uniformly correct. A bare leading fd digit is only
    dropped when the NEXT token is itself a redirection operator.
    """
    out: list[str] = []
    i = 0
    n = len(seg)
    while i < n:
        t = seg[i]
        if t.isdigit() and i + 1 < n and _REDIR.match(seg[i + 1]):
            i += 1
            continue
        if _REDIR.match(t):
            i += 1
            if i < n:
                i += 1  # drop the redirect's target operand too
            continue
        out.append(t)
        i += 1
    return out


def analyze_segment(seg: list[str]) -> dict[str, Any] | None:
    """Scan ONE redirection-stripped segment for a grep/rg-class invocation.

    Returns ``{"term", "paths", "includes"}`` for a search-class segment
    (recursive grep/egrep/fgrep, or any rg/ag), else ``None``. Recursion is the
    gate for grep: plain ``grep pat file`` is a line lookup, not a search.
    """
    n = len(seg)
    i = 0
    while i < n:
        base = seg[i].split("/")[-1]
        if base in ("rg", "ag"):
            term = ""
            paths: list[str] = []
            got = False
            j = i + 1
            while j < n:
                t = seg[j]
                if t.startswith("-"):
                    j += 1
                    continue
                if not got:
                    term = t
                    got = True
                else:
                    paths.append(t)
                j += 1
            return {"term": term, "paths": paths, "includes": []}
        if base in ("grep", "egrep", "fgrep"):
            recursive = False
            got = False
            term = ""
            paths = []
            includes: list[str] = []
            j = i + 1
            while j < n:
                t = seg[j]
                if t == "--":
                    j += 1
                    continue
                if t.startswith("--include="):
                    recursive = True
                    includes.append(t.split("=", 1)[1])
                    j += 1
                    continue
                if t == "--include":
                    recursive = True
                    j += 1
                    if j < n:
                        includes.append(seg[j])
                        j += 1
                    continue
                if t == "--recursive":
                    recursive = True
                    j += 1
                    continue
                if t.startswith("--"):
                    j += 1
                    continue
                if t.startswith("-") and len(t) > 1:
                    if "r" in t or "R" in t:
                        recursive = True
                    j += 1
                    continue
                if not got:
                    term = t
                    got = True
                else:
                    paths.append(t)
                j += 1
            if recursive:
                return {"term": term, "paths": paths, "includes": includes}
            return None
        i += 1
    return None


def _load_indexed(project_root: Path) -> tuple[set[str], set[str]]:
    """The indexed set from the persisted folder manifests — ground truth.

    Returns (files, dirs): every indexed file's realpath and every ancestor
    directory of one. A path is "indexed" iff it is an indexed file or a
    directory containing >=1 indexed file; every real exclusion brainpalace
    applied is honored with no hardcoded guesses.
    """
    files: set[str] = set()
    for mp in _glob.glob(str(project_root / ".brainpalace" / "manifests" / "*.json")):
        try:
            with open(mp, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        for k in d.get("files") or {}:
            files.add(os.path.realpath(k))
    dirs: set[str] = set()
    for f in files:
        d = os.path.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    return files, dirs


def _resolve(path: str, cwd: Path) -> str:
    if not path:
        return os.path.realpath(str(cwd))  # no operand -> the search runs in cwd
    p = os.path.expanduser(path)
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(str(cwd), p))


def analyze_bash_command(
    command: str, project_root: Path, cwd: Path | None = None
) -> BashSearchAnalysis:
    """Analyze one Bash command string against this project's index."""
    segments = [strip_redirections(s) for s in split_segments(tokenize(command))]
    segments = [s for s in segments if s]
    hits: list[dict[str, Any]] = []
    other: list[list[str]] = []
    for seg in segments:
        hit = analyze_segment(seg)
        if hit is not None:
            hits.append(hit)
        else:
            other.append(seg)
    if not hits:
        return BashSearchAnalysis()

    grep_hits = [h for h in hits if classify(h["term"]) == "grep"]
    bm25_hits = [h for h in hits if classify(h["term"]) != "grep"]
    if grep_hits:
        chosen, cls = grep_hits[0], "grep"
    elif len(bm25_hits) > 1:
        chosen, cls = bm25_hits[0], "multi"
    else:
        chosen, cls = bm25_hits[0], "bm25"

    files, dirs = _load_indexed(project_root)
    base = cwd or project_root
    resolved = [_resolve(p, base) for p in chosen["paths"]] or [_resolve("", base)]
    target_indexed = any(ap in files or ap in dirs for ap in resolved)

    pure_search = len(hits) == 1 and all(
        seg[0].split("/")[-1] in _READONLY_FILTERS for seg in other
    )
    return BashSearchAnalysis(
        is_search=True,
        term=chosen["term"],
        classify=cls,
        target_indexed=target_indexed,
        pure_search=pure_search,
    )


def is_indexed_target(path: str | None, project_root: Path, cwd: Path) -> bool:
    """True when ``path`` (or ``cwd`` when None) is an indexed file or a
    directory containing >=1 indexed file, per the folder manifests.

    The Grep-tool counterpart of the Bash operand check: same manifest ground
    truth, same fail-open direction (missing/empty manifest -> False, i.e.
    allow the native search).
    """
    files, dirs = _load_indexed(project_root)
    ap = _resolve(path or "", cwd)
    return ap in files or ap in dirs

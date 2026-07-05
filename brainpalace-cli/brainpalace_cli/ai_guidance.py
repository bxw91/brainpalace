"""Single-source AI-guidance loader, slicer, and renderer.

Reads the bundled ``data/ai_guidance.md`` — the ONE source of truth for
AI-facing BrainPalace usage guidance — and renders it for each consuming
surface (SessionStart hook, MCP ``instructions=``/``ai_guide`` tool, generated
plugin SKILL.md). See CLAUDE.md → "AI-guidance parity".

CORE is a literal slice of FULL (marker-delimited), never a second copy — so the
tiers cannot drift. All output is byte-deterministic: ``version`` /
``last_validated`` come from the source's declared ``meta:`` line, never
``today()`` (determinism + honest freshness). Fail-soft: a missing/garbled
source returns empty strings rather than raising, so a hook or MCP connect is
never blocked.
"""

from __future__ import annotations

import re
from importlib.resources import files

#: Bundled source resource (package-relative).
_PACKAGE = "brainpalace_cli.data"
_RESOURCE = "ai_guidance.md"

_NUDGE_OPEN = "<!--NUDGE-->"
_NUDGE_CLOSE = "<!--/NUDGE-->"
_CORE_OPEN = "<!--CORE-->"
_CORE_CLOSE = "<!--/CORE-->"
#: Every tier marker — stripped from rendered output (tiers nest: NUDGE ⊂ CORE ⊂ FULL).
_ALL_MARKERS = (_NUDGE_OPEN, _NUDGE_CLOSE, _CORE_OPEN, _CORE_CLOSE)
_META_RE = re.compile(
    r"meta:\s*version=(?P<version>\S+)\s+last_validated=(?P<date>\S+)"
)
#: Leading HTML comment block (the maintainer header) — stripped from all output.
_LEADING_COMMENT_RE = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)

#: Skill frontmatter template. This is the ONE skill-specific bit that does not
#: live in the shared source (MCP/hook do not need ``name``/``description``/
#: ``allowed-tools``). ``{version}`` / ``{last_validated}`` are filled from the
#: source meta so the generated SKILL.md stays byte-deterministic.
_SKILL_FRONTMATTER = """\
---
name: using-brainpalace
description: |
  Expert BrainPalace skill for document search with BM25 keyword, semantic
  vector, hybrid, graph, multi, compute, scan, absence, and timeline
  retrieval modes.
  Use when asked to "search documentation", "query domain", "find in docs",
  "bm25 search", "hybrid search", "semantic search", "graph search", "multi search",
  "compute query", "scan sessions", "absence query", "timeline query",
  "find dependencies", "code relationships", "searching knowledge base",
  "querying indexed documents", "finding code references", "exploring codebase",
  "what calls this function", "find imports", "trace dependencies",
  "brain search", "brain query", "knowledge base search",
  "cache management", "clear embedding cache", "cache hit rate", or "cache status".
  Supports multi-instance architecture with automatic server discovery.
  GraphRAG mode enables relationship-aware queries for code dependencies and
  entity connections.
  Pluggable providers for embeddings (OpenAI, Cohere, Ollama) and summarization
  (Anthropic, OpenAI, Gemini, Grok, Ollama).
  Supports multiple runtimes (Claude Code, OpenCode, Gemini CLI) with shared
  .brainpalace/ data directory.
license: MIT
allowed-tools:
  - Bash
  - Read
metadata:
  version: {version}
  category: ai-tools
  author: bxw91
  last_validated: {last_validated}
---
"""


def load_source() -> str:
    """Return the raw bundled ``ai_guidance.md``, or ``""`` if unavailable."""
    try:
        return files(_PACKAGE).joinpath(_RESOURCE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return ""


def parse_meta(src: str | None = None) -> dict[str, str]:
    """Extract ``version`` and ``last_validated`` from the source ``meta:`` line."""
    text = load_source() if src is None else src
    m = _META_RE.search(text)
    if not m:
        return {"version": "0.0.0", "last_validated": "unknown"}
    return {"version": m.group("version"), "last_validated": m.group("date")}


def _body(src: str) -> str:
    """Strip the leading maintainer comment block from the source."""
    return _LEADING_COMMENT_RE.sub("", src, count=1)


def _strip_markers(text: str) -> str:
    """Remove every tier marker (and any newline it sits on) from output."""
    for marker in _ALL_MARKERS:
        text = text.replace(marker + "\n", "").replace(marker, "")
    return text


def _slice(text: str, open_tok: str, close_tok: str) -> str:
    """Return the inner content between a marker pair, markers stripped."""
    start = text.find(open_tok)
    end = text.find(close_tok)
    if start == -1 or end == -1 or end < start:
        return ""
    inner = text[start + len(open_tok) : end]
    return _strip_markers(inner).strip()


def nudge(src: str | None = None) -> str:
    """Return the NUDGE slice — the minimal per-session reminder."""
    text = load_source() if src is None else src
    return _slice(text, _NUDGE_OPEN, _NUDGE_CLOSE)


def core(src: str | None = None) -> str:
    """Return the CORE slice (nested NUDGE markers stripped), or ``""`` if absent."""
    text = load_source() if src is None else src
    return _slice(text, _CORE_OPEN, _CORE_CLOSE)


def full(src: str | None = None) -> str:
    """Return the FULL body: header comment stripped, all tier markers removed."""
    text = load_source() if src is None else src
    return _strip_markers(_body(text)).strip()


def render(tier: str = "full", fmt: str = "markdown") -> str:
    """Render guidance for a consumer.

    tier: ``nudge`` (minimal per-session reminder) | ``core`` (decision contract)
          | ``full`` (everything).
    fmt:  ``markdown``/``hook``/``mcp`` emit the tier text as-is; ``skill`` emits
          the full SKILL.md (frontmatter + FULL body), forcing ``tier=full``.
    """
    src = load_source()
    if fmt == "skill":
        meta = parse_meta(src)
        return (
            _SKILL_FRONTMATTER.format(
                version=meta["version"], last_validated=meta["last_validated"]
            )
            + "\n"
            + full(src)
            + "\n"
        )
    if tier == "nudge":
        return nudge(src)
    if tier == "core":
        return core(src)
    return full(src)

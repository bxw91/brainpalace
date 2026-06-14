# brainpalace-cli/brainpalace_cli/doc_sync/markers.py
"""Strict grammar for machine-owned GENERATED blocks. Errors loudly rather than
guessing — silent guesses are how the ai_guidance marker bug happened."""

from __future__ import annotations

OPEN_FMT = "<!--GENERATED:{name}-->"
CLOSE = "<!--/GENERATED-->"


class MarkerError(ValueError):
    pass


def _open(name: str) -> str:
    return OPEN_FMT.format(name=name)


def find_block(text: str, name: str) -> str:
    open_tag = _open(name)
    n_open = text.count(open_tag)
    if n_open == 0:
        raise MarkerError(f"missing block open {open_tag!r}")
    if n_open > 1:
        raise MarkerError(f"duplicate/nested block {open_tag!r}")
    start = text.index(open_tag) + len(open_tag)
    rest = text[start:]
    if CLOSE not in rest:
        raise MarkerError(f"unbalanced block {open_tag!r}: no {CLOSE}")
    inner = rest[: rest.index(CLOSE)]
    if open_tag in inner:
        raise MarkerError(f"nested block {open_tag!r}")
    return inner.strip("\n")


def replace_block(text: str, name: str, new_inner: str) -> str:
    find_block(text, name)  # validates grammar
    open_tag = _open(name)
    start = text.index(open_tag) + len(open_tag)
    rest = text[start:]
    end = rest.index(CLOSE)
    return text[:start] + "\n" + new_inner + "\n" + rest[end:]

# brainpalace-cli/tests/doc_sync/test_markers.py
import pytest

from brainpalace_cli.doc_sync.markers import (
    CLOSE,
    OPEN_FMT,
    MarkerError,
    find_block,
    replace_block,
)

DOC = f"""# Title

{OPEN_FMT.format(name="flags")}
old content
{CLOSE}

## Prose
keep me
"""


def test_find_block_returns_inner():
    assert find_block(DOC, "flags") == "old content"


def test_replace_block_swaps_only_inner_and_preserves_prose():
    out = replace_block(DOC, "flags", "NEW")
    assert "NEW" in out
    assert "old content" not in out
    assert "keep me" in out  # prose untouched


def test_missing_block_raises():
    with pytest.raises(MarkerError):
        find_block("no markers here", "flags")


def test_unbalanced_block_raises():
    bad = f'{OPEN_FMT.format(name="flags")}\nx\n'  # no close
    with pytest.raises(MarkerError):
        find_block(bad, "flags")


def test_nested_same_name_raises():
    nested = (
        f'{OPEN_FMT.format(name="flags")}\n'
        f'{OPEN_FMT.format(name="flags")}\n{CLOSE}\n{CLOSE}\n'
    )
    with pytest.raises(MarkerError):
        find_block(nested, "flags")

import textwrap
from pathlib import Path

from brainpalace_cli.doc_sync.facts import CommandFact, FlagFact
from brainpalace_cli.doc_sync.generator import (
    regenerate_command_doc,
    regenerate_modes_block,
)
from brainpalace_cli.doc_sync.markers import CLOSE, OPEN_FMT, find_block
from brainpalace_cli.doc_sync.serializer import NO_FLAGS_TEXT


def _doc(tmp_path: Path) -> Path:
    p = tmp_path / "brainpalace-index.md"
    p.write_text(
        textwrap.dedent(
            f"""\
        ---
        name: brainpalace-index
        command: index
        description: x
        parameters:
          - name: stale
            type: bool
            required: false
            default: false
        ---
        # Index

        ## Purpose
        Human prose that MUST survive.

        ### Flags
        {OPEN_FMT.format(name="flags")}
        old table
        {CLOSE}
        """
        )
    )
    return p


def test_regenerate_updates_frontmatter_and_table_preserving_prose(tmp_path):
    p = _doc(tmp_path)
    cmd = CommandFact(
        "index", flags=[FlagFact("force", "bool", False, False, "Force it")]
    )
    regenerate_command_doc(p, cmd)
    out = p.read_text()
    assert "Human prose that MUST survive." in out  # prose preserved
    assert "name: force" in out  # frontmatter regenerated
    assert "name: stale" not in out  # old contract gone
    assert "--force" in out and "old table" not in out  # generated block refreshed


def test_regenerate_is_idempotent(tmp_path):
    p = _doc(tmp_path)
    cmd = CommandFact(
        "index", flags=[FlagFact("force", "bool", False, False, "Force it")]
    )
    regenerate_command_doc(p, cmd)
    first = p.read_text()
    regenerate_command_doc(p, cmd)
    assert p.read_text() == first  # byte-stable second run


# ----------------------------------------------------- D4: flags-block normalization
def _doc_no_flags_block(tmp_path: Path) -> Path:
    """A command doc with an empty `parameters:` (matches a flagless
    CommandFact) and NO `### Flags` section at all."""
    p = tmp_path / "brainpalace-ingest.md"
    p.write_text(
        textwrap.dedent(
            """\
        ---
        name: brainpalace-ingest
        command: ingest
        description: x
        parameters:
        ---
        # Ingest

        ## Purpose
        Human prose that MUST survive.
        """
        )
    )
    return p


def test_regenerate_flagless_command_normalizes_stale_flags_block(tmp_path):
    """(a) A command that lost all its flags (e.g. `ingest` becoming a group)
    keeps a NON-EMPTY, non-stale flags block: its content is replaced with the
    explicit no-flags one-liner instead of being left stale forever."""
    p = _doc(tmp_path)  # has a stale "old table" flags block + stale params
    cmd = CommandFact("index", flags=[])
    regenerate_command_doc(p, cmd)
    out = p.read_text()
    assert "Human prose that MUST survive." in out  # prose preserved
    assert "old table" not in out  # stale content gone
    assert "name: stale" not in out  # stale frontmatter contract gone
    assert find_block(out, "flags").strip() == NO_FLAGS_TEXT
    assert OPEN_FMT.format(name="flags") in out and CLOSE in out  # markers kept


def test_regenerate_flagless_command_without_block_is_untouched(tmp_path):
    """(b) A flagless command with NO flags block is left alone — no block is
    ever auto-appended for a command that has nothing to document."""
    p = _doc_no_flags_block(tmp_path)
    before = p.read_text()
    cmd = CommandFact("ingest", flags=[])
    regenerate_command_doc(p, cmd)
    assert p.read_text() == before
    assert "### Flags" not in p.read_text()


def test_regenerate_flagged_command_behavior_unchanged(tmp_path):
    """(c) A command that DOES have flags keeps rendering the real table
    (D4 only changes the flagless path)."""
    p = _doc(tmp_path)
    cmd = CommandFact(
        "index", flags=[FlagFact("force", "bool", False, False, "Force it")]
    )
    regenerate_command_doc(p, cmd)
    out = p.read_text()
    assert "--force" in out
    assert "old table" not in out
    assert find_block(out, "flags").strip() != NO_FLAGS_TEXT


def test_regenerate_flagless_normalization_is_idempotent(tmp_path):
    """(d) A second --fix run over an already-normalized flagless doc produces
    zero diff — required so `brainpalace-ingest.md` doesn't churn every run."""
    p = _doc(tmp_path)
    cmd = CommandFact("index", flags=[])
    regenerate_command_doc(p, cmd)
    first = p.read_text()
    regenerate_command_doc(p, cmd)
    assert p.read_text() == first


MODES = ["vector", "hybrid", "scan"]


def test_regenerate_modes_block_refreshes_existing_block(tmp_path):
    p = tmp_path / "README.md"
    p.write_text(
        "# Readme\n## Search Modes\n"
        f"{OPEN_FMT.format(name='modes')}\nstale\n{CLOSE}\n## Next\nkeep\n"
    )
    changed = regenerate_modes_block(p, MODES, style="grid")
    out = p.read_text()
    assert changed is True
    assert "`SCAN`" in find_block(out, "modes")
    assert "stale" not in out
    assert "keep" in out


def test_regenerate_modes_block_skips_file_without_block(tmp_path):
    p = tmp_path / "NOBLOCK.md"
    p.write_text("# Nothing to see\n")
    changed = regenerate_modes_block(p, MODES, style="table")
    assert changed is False
    assert p.read_text() == "# Nothing to see\n"  # untouched, never appended


def test_regenerate_modes_block_commands_style(tmp_path):
    p = tmp_path / "USER_GUIDE.md"
    p.write_text(f"# Guide\n{OPEN_FMT.format(name='modes')}\nold\n{CLOSE}\n")
    regenerate_modes_block(p, MODES, style="commands")
    inner = find_block(p.read_text(), "modes")
    assert "/brainpalace-query --mode scan" in inner
    assert "/brainpalace-query`" in inner  # hybrid default row present

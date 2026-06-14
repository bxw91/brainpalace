import textwrap
from pathlib import Path

from brainpalace_cli.doc_sync.facts import CommandFact, FlagFact
from brainpalace_cli.doc_sync.generator import regenerate_command_doc
from brainpalace_cli.doc_sync.markers import CLOSE, OPEN_FMT


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

# brainpalace-cli/tests/doc_sync/test_body_table.py
import textwrap
from pathlib import Path

from brainpalace_cli.doc_sync.facts import CommandFact, FlagFact
from brainpalace_cli.doc_sync.generator import regenerate_command_doc
from brainpalace_cli.doc_sync.markers import find_block
from brainpalace_cli.doc_sync.serializer import render_flags_section

CF = CommandFact("index", flags=[FlagFact("force", "bool", False, False, "Force")])


def test_render_flags_section_has_heading_and_generated_block():
    out = render_flags_section(CF)
    assert out.startswith("### Flags\n")
    # the section embeds a valid GENERATED:flags block whose inner is the table
    assert "--force" in find_block(out, "flags")


def _doc_no_block(tmp_path: Path) -> Path:
    p = tmp_path / "brainpalace-index.md"
    p.write_text(
        textwrap.dedent(
            """\
        ---
        name: brainpalace-index
        description: x
        parameters:
          - name: force
            type: bool
            required: false
            default: false
        ---
        # Index
        ## Purpose
        Keep me.
        """
        )
    )
    return p


def test_regenerate_creates_flags_block_when_absent(tmp_path):
    p = _doc_no_block(tmp_path)
    regenerate_command_doc(p, CF)
    out = p.read_text()
    assert "<!--GENERATED:flags-->" in out
    assert "--force" in out
    assert "Keep me." in out  # prose preserved


def test_regenerate_create_is_idempotent(tmp_path):
    p = _doc_no_block(tmp_path)
    regenerate_command_doc(p, CF)
    first = p.read_text()
    regenerate_command_doc(p, CF)
    assert p.read_text() == first


def test_regenerate_skips_block_when_command_has_no_flags(tmp_path):
    p = _doc_no_block(tmp_path)
    regenerate_command_doc(p, CommandFact("index", flags=[]))
    assert "<!--GENERATED:flags-->" not in p.read_text()

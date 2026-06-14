import textwrap

from brainpalace_cli.doc_sync.checkers.modes import ModesChecker
from brainpalace_cli.doc_sync.facts import DriftKind, InterfaceSnapshot
from brainpalace_cli.doc_sync.generator import regenerate_query_modes
from brainpalace_cli.doc_sync.markers import find_block
from brainpalace_cli.doc_sync.serializer import render_modes_table

MODES = ["vector", "bm25", "hybrid", "graph", "multi"]


def test_render_modes_table_byte_stable_and_lists_all():
    out = render_modes_table(MODES)
    assert out == render_modes_table(MODES)
    for m in MODES:
        assert f"`{m}`" in out


def test_regenerate_query_modes_creates_block_preserving_prose(tmp_path):
    p = tmp_path / "brainpalace-query.md"
    p.write_text(
        textwrap.dedent(
            """\
        ---
        name: brainpalace-query
        ---
        # Query
        ## Modes
        <!--GENERATED:modes-->
        old
        <!--/GENERATED-->
        ## Notes
        keep me
        """
        )
    )
    regenerate_query_modes(p, MODES)
    out = p.read_text()
    assert "`hybrid`" in find_block(out, "modes")
    assert "keep me" in out and "old" not in out


def _snap(modes):
    return InterfaceSnapshot(1, "9.9.9", commands=[], modes=modes)


def _query_doc(tmp_path, inner):
    (tmp_path / "brainpalace-query.md").write_text(
        f"---\nname: brainpalace-query\n---\n# Query\n## Modes\n"
        f"<!--GENERATED:modes-->\n{inner}\n<!--/GENERATED-->\n"
    )


def test_canonical_block_mismatch_flagged(tmp_path):
    _query_doc(tmp_path, "| Mode | Description |\n|------|------|\n| `vector` |  |")
    recs = ModesChecker(docs_dir=tmp_path).check(_snap(MODES))
    assert any(r.kind is DriftKind.MISMATCH and r.source_id == "query" for r in recs)


def test_canonical_block_clean(tmp_path):
    _query_doc(tmp_path, render_modes_table(MODES))
    recs = ModesChecker(docs_dir=tmp_path).check(_snap(MODES))
    assert [r for r in recs if r.kind is DriftKind.MISMATCH] == []


def test_referential_dangling_mode_in_other_doc(tmp_path):
    _query_doc(tmp_path, render_modes_table(MODES))
    (tmp_path / "brainpalace-foo.md").write_text(
        "---\nname: x\n---\n`brainpalace query --mode ghost`\n"
    )
    recs = ModesChecker(docs_dir=tmp_path).check(_snap(MODES))
    assert any(r.source_id == "ghost" and r.kind is DriftKind.EXTRA for r in recs)

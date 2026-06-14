import textwrap

from brainpalace_cli.doc_sync.checkers.mcp import McpChecker
from brainpalace_cli.doc_sync.facts import DriftKind, InterfaceSnapshot
from brainpalace_cli.doc_sync.generator import regenerate_mcp_tools
from brainpalace_cli.doc_sync.introspect import mcp_tool_names
from brainpalace_cli.doc_sync.markers import find_block
from brainpalace_cli.doc_sync.serializer import render_mcp_tools_table

TOOLS = ["ai_guide", "query", "status"]


def _snap(tools):
    return InterfaceSnapshot(1, "9.9.9", mcp_tools=tools)


def _mcp_doc(tmp_path, inner):
    (tmp_path / "brainpalace-mcp.md").write_text(
        f"---\nname: brainpalace-mcp\n---\n## Tools\n"
        f"<!--GENERATED:mcp-tools-->\n{inner}\n<!--/GENERATED-->\n"
    )


def test_mcp_canonical_block_mismatch(tmp_path):
    _mcp_doc(tmp_path, "| Tool | Description |\n|------|------|\n| `query` |  |")
    recs = McpChecker(docs_dir=tmp_path).check(_snap(["query", "status"]))
    assert any(r.kind is DriftKind.MISMATCH for r in recs)


def test_mcp_canonical_block_clean(tmp_path):
    _mcp_doc(tmp_path, render_mcp_tools_table(["query", "status"]))
    recs = McpChecker(docs_dir=tmp_path).check(_snap(["query", "status"]))
    assert [r for r in recs if r.kind is DriftKind.MISMATCH] == []


def test_mcp_tool_names_from_registry():
    names = set(mcp_tool_names())
    assert {"query", "status", "ai_guide"} <= names


def test_render_mcp_tools_table_lists_all_byte_stable():
    out = render_mcp_tools_table(TOOLS)
    assert out == render_mcp_tools_table(TOOLS)
    for t in TOOLS:
        assert f"`{t}`" in out


def test_regenerate_mcp_tools_block_preserves_prose(tmp_path):
    p = tmp_path / "brainpalace-mcp.md"
    p.write_text(
        textwrap.dedent(
            """\
        ---
        name: brainpalace-mcp
        ---
        # MCP
        ## Tools
        <!--GENERATED:mcp-tools-->
        old
        <!--/GENERATED-->
        ## Notes
        keep me
        """
        )
    )
    regenerate_mcp_tools(p, TOOLS)
    out = p.read_text()
    assert "`query`" in find_block(out, "mcp-tools")
    assert "keep me" in out and "old" not in out

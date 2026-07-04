from brainpalace_cli import config_fields as cf
from brainpalace_cli import config_parity


def test_section_and_nested_registered():
    assert "graph_indexing" in cf.SECTION_MODELS
    assert "graph_indexing.lsp" in cf.NESTED_MODELS


def test_lsp_leaf_specs_exist():
    for leaf in ("mode", "python", "typescript"):
        assert f"graph_indexing.lsp.{leaf}" in cf.FIELD_SPECS


def test_mode_is_choice_with_options():
    spec = cf.FIELD_SPECS["graph_indexing.lsp.mode"]
    assert spec.widget == "choice"
    assert set(cf.options_for(spec.options_ref)) == {"auto", "on", "off"}


def test_group_order_has_graph_indexing():
    assert any(g == "graph_indexing" for g, _ in cf.GROUP_ORDER)
    assert "graph_indexing" in cf.GROUP_DESCRIPTIONS


def test_parity_still_clean():
    assert config_parity.check() == []

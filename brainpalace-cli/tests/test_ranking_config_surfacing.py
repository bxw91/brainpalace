import pytest

from brainpalace_cli import config_fields as cf


def test_ranking_section_registered():
    assert "ranking" in cf.SECTION_MODELS
    assert cf.SECTION_MODELS["ranking"].model_fields["doc_weight"].default == 0.5


def test_doc_weight_renders_as_float_field_in_terminal_grid():
    specs = cf.build_specs()  # the CLI config grid / wizard source
    spec = next(s for s in specs.values() if s.dotpath == "ranking.doc_weight")
    assert spec.widget == "float"
    assert (
        "trusted vs code" in spec.help.lower() or "documentation" in spec.help.lower()
    )


def test_group_order_has_ranking_and_matches_dashboard_order():
    # The CLI↔dashboard parity assertion needs the REAL ui_schema.SECTION_ORDER, so
    # faking the package would defeat it. The dashboard is optional in the CLI env
    # (absent in the py3.11 CLI gate + CI rehearsal), so skip when it can't be
    # imported — the py3.12 Dashboard Gate (all three packages present) is the real
    # enforcer of this parity.
    ui_schema = pytest.importorskip("brainpalace_dashboard.ui_schema")

    assert ("ranking", "Retrieval Ranking") in cf.GROUP_ORDER
    assert cf.GROUP_ORDER == ui_schema.SECTION_ORDER  # parity
    assert "ranking" in cf.GROUP_DESCRIPTIONS

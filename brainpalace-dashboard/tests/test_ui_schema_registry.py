"""Milestone A guard: ui_schema sources order + help + label from the CLI field
registry, with byte-for-byte identical output (golden snapshot).
"""

import json
from pathlib import Path

from brainpalace_cli import config_fields as cf

from brainpalace_dashboard.ui_schema import SECTION_ORDER, build_ui_schema

GOLDEN = Path(__file__).parent / "fixtures" / "ui_schema_golden.json"


def test_ui_schema_matches_golden():
    current = build_ui_schema()
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=2, sort_keys=True))
    assert current == json.loads(GOLDEN.read_text()), "ui_schema output changed"


def test_group_order_equals_section_order():
    assert cf.GROUP_ORDER == SECTION_ORDER


def test_section_descriptions_sourced_from_cli():
    from brainpalace_dashboard.ui_schema import SECTION_DESCRIPTIONS

    assert SECTION_DESCRIPTIONS == cf.GROUP_DESCRIPTIONS


def test_grid_hidden_fields_are_also_dashboard_hidden():
    # A field the CLI review grid suppresses must be hidden on the dashboard too
    # (parity, single-sourced from cf.GRID_HIDDEN_FIELDS).
    from brainpalace_dashboard.ui_schema import DASHBOARD_HIDDEN_FIELDS

    assert set(cf.GRID_HIDDEN_FIELDS) <= set(DASHBOARD_HIDDEN_FIELDS)


def test_default_fallbacks_single_sourced():
    """The settings-fallback map is owned by the CLI registry; the dashboard
    re-exports the same object (no divergent copy)."""
    from brainpalace_dashboard.ui_schema import DEFAULT_FALLBACKS

    assert DEFAULT_FALLBACKS is cf.DEFAULT_FALLBACKS


def test_dashboard_and_init_grid_resolve_same_default():
    """Every dashboard-rendered field must resolve to the SAME effective code
    default in the CLI `init` review grid. Regression guard: graphrag.* and
    compute.min_confidence default to None in the model (real default in
    settings.py) and showed empty in `init` while the dashboard showed 0.7/True
    — the two surfaces must agree, from one source (cf.DEFAULT_FALLBACKS)."""
    schema = build_ui_schema()
    for section in schema["sections"]:
        for field in section["fields"]:
            if "default" not in field:
                continue
            dotpath = field["dotpath"]
            cli_default, _ = cf.resolve_value_layered(dotpath, {}, {})
            assert cli_default == field["default"], (
                f"{dotpath}: dashboard default {field['default']!r} != "
                f"init-grid default {cli_default!r}"
            )


def test_section_split_and_field_order_match_init_grid():
    """The dashboard Config tab and the `bp init` review grid must render the SAME
    sections in the SAME order with the SAME field order — single-sourced from the
    CLI registry. Guards the session_archiving/session_indexing split and the
    canonical intra-section order so a change to either propagates to both."""
    schema = build_ui_schema()

    # 1. Section split + order: Session Archiving immediately precedes Session
    #    Vector Indexing on the dashboard...
    keys = [s["key"] for s in schema["sections"]]
    assert "session_archiving" in keys and "session_indexing" in keys
    assert keys.index("session_archiving") + 1 == keys.index("session_indexing")
    #    ...and the init grid divisions follow the same relative order (it hides
    #    the runtime server/project sections, so it's a subsequence).
    from brainpalace_cli import config_review as cr

    div_keys = [g for g, _label in cr._divisions()]
    assert div_keys == [k for k in keys if k in set(div_keys)]
    si = div_keys.index("session_indexing")
    assert div_keys[si - 1] == "session_archiving"

    # 2. Intra-section field order: for each dashboard section, the flat fields'
    #    dotpaths (skipping nested group widgets) match cf.group_fields() order.
    for section in schema["sections"]:
        # Compare only registry-backed fields (modelless server/project have no
        # spec — their order isn't cf-driven and is excluded from the contract).
        dash_dotpaths = [
            f["dotpath"]
            for f in section["fields"]
            if f.get("widget") != "group" and f["dotpath"] in cf.FIELD_SPECS
        ]
        cf_dotpaths = [
            s.dotpath
            for s in cf.group_fields(section["key"])
            if s.dotpath in set(dash_dotpaths)
        ]
        assert dash_dotpaths == cf_dotpaths, f"field order drift in {section['key']}"


def test_cli_and_dashboard_introspection_agree():
    """Parallel impls: cf._auto_widget vs model_introspect.widget_and_options."""
    from brainpalace_dashboard import model_introspect as mi

    # model_introspect names widgets toggle/enum/dict/stringlist; the registry
    # names them bool/choice and folds dict/list into text. Normalize mi -> cf
    # naming, then assert they agree (cf additionally splits numeric `text` into
    # int/float, which mi lumps under text).
    norm = {"toggle": "bool", "enum": "choice", "dict": "text", "stringlist": "text"}
    for _section, model in cf.SECTION_MODELS.items():
        for fname, finfo in model.model_fields.items():
            w_mi, _ = mi.widget_and_options(finfo.annotation)
            w_cf = cf._auto_widget(finfo.annotation)
            m = norm.get(w_mi, w_mi)
            assert m == w_cf or (
                m == "text" and w_cf in ("text", "float", "int")
            ), f"{_section}.{fname}: mi={w_mi} cf={w_cf}"

# brainpalace-cli/tests/doc_sync/test_serializer.py
import yaml

from brainpalace_cli.doc_sync.facts import CommandFact, FlagFact
from brainpalace_cli.doc_sync.serializer import render_flags_table, render_params_yaml

CF = CommandFact(
    name="index",
    flags=[
        FlagFact("force", "bool", False, False, "Force re-indexing"),
        FlagFact("include-code", "bool", True, False, "Include code files"),
    ],
)


def test_render_flags_table_is_byte_stable():
    assert render_flags_table(CF) == render_flags_table(CF)


def test_render_flags_table_keeps_definition_order():
    out = render_flags_table(CF)
    assert out.index("--force") < out.index("--include-code")  # definition order


def test_render_params_yaml_is_a_list_block():
    out = render_params_yaml(CF)
    assert out.startswith("parameters:")
    assert "- name: force" in out
    assert "- name: include-code" in out
    # default rendered, description carried (description is prose but seeded here)
    assert "default: false" in out


def test_boolish_flag_name_round_trips_through_yaml():
    # YAML 1.1 coerces bare `yes`/`no`/`on`/`off` to bools; the flag name MUST be
    # quoted so safe_load reads back the original string (e.g. `--yes`).
    cf = CommandFact(
        name="init",
        flags=[FlagFact("yes", "bool", False, False, "Skip confirmation")],
    )
    out = render_params_yaml(cf)
    assert '- name: "yes"' in out
    parsed = yaml.safe_load(out)
    assert [p["name"] for p in parsed["parameters"]] == ["yes"]

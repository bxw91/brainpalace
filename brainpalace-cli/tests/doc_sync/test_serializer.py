# brainpalace-cli/tests/doc_sync/test_serializer.py
import yaml

from brainpalace_cli.doc_sync.facts import CommandFact, FlagFact
from brainpalace_cli.doc_sync.serializer import (
    render_flags_table,
    render_modes_commands,
    render_modes_grid,
    render_modes_table,
    render_params_yaml,
)

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


MODES = ["vector", "hybrid", "scan", "timeline"]


def test_render_modes_table_fills_descriptions_from_mode_meta():
    out = render_modes_table(MODES)
    lines = out.splitlines()
    assert lines[0] == "| Mode | Description |"
    assert "| `vector` | Semantic similarity search |" in out
    assert "| `scan` |" in out and "archived session transcripts" in out
    assert "| `timeline` |" in out and "supersession history" in out


def test_render_modes_table_is_byte_stable():
    assert render_modes_table(MODES) == render_modes_table(MODES)


def test_render_modes_grid_shape_and_case():
    out = render_modes_grid(MODES)
    lines = out.splitlines()
    assert lines[0] == "| Mode | Best For | Example Query |"
    assert '| `VECTOR` | Conceptual understanding | "Explain the architecture" |' in out
    assert "| `HYBRID` |" in out
    assert "| `SCAN` |" in out
    assert "| `TIMELINE` |" in out


def test_render_modes_commands_shape_hybrid_is_default():
    out = render_modes_commands(MODES)
    lines = out.splitlines()
    assert lines[0] == "| Command | Description | Best For |"
    assert "| `/brainpalace-query` | Vector + BM25 fusion (default) |" in out
    assert "`/brainpalace-query --mode vector`" in out
    assert "`/brainpalace-query --mode scan`" in out
    assert "`/brainpalace-query --mode timeline`" in out
    assert "`/brainpalace-query --mode hybrid`" not in out

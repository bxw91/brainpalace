# brainpalace-cli/tests/doc_sync/test_facts.py
from brainpalace_cli.doc_sync.facts import (
    CommandFact,
    DriftKind,
    DriftRecord,
    FlagFact,
    canon_bool,
    canon_default,
    canon_flag_name,
)


def test_canon_bool_unifies_forms():
    assert canon_bool(True) is True
    assert canon_bool("true") is True
    assert canon_bool("True") is True
    assert canon_bool("false") is False
    assert canon_bool(False) is False


def test_canon_default_unifies_empty_forms():
    assert canon_default(None) is None
    assert canon_default("-") is None
    assert canon_default("") is None
    assert canon_default("auto") == "auto"
    assert canon_default(True) is True


def test_canon_flag_name_strips_short_alias_keeps_long():
    # Click params expose ("-m", "--mode"); we key on the long name without dashes.
    assert canon_flag_name(["-m", "--mode"]) == "mode"
    assert canon_flag_name(["--include-code"]) == "include-code"


def test_flagfact_equality_is_contract_only_not_description():
    a = FlagFact(
        name="force", type="bool", default=False, required=False, description="X"
    )
    b = FlagFact(
        name="force",
        type="bool",
        default=False,
        required=False,
        description="totally different",
    )
    assert a == b  # description is NOT part of contract equality


def test_command_fact_holds_flags_and_id():
    cf = CommandFact(
        name="index",
        hidden=False,
        deprecated=False,
        flags=[FlagFact("force", "bool", False, False, "")],
    )
    assert cf.name == "index"
    assert cf.flags[0].name == "force"


def test_drift_record_shape():
    d = DriftRecord(
        surface="cli",
        source_id="index",
        doc_path="x.md",
        kind=DriftKind.MISSING,
        detail="no doc",
    )
    assert d.kind is DriftKind.MISSING

import textwrap
from pathlib import Path

from brainpalace_cli.doc_sync.allowlist import UNDOCUMENTED_COMMANDS
from brainpalace_cli.doc_sync.checkers.cli_commands import CliCommandsChecker
from brainpalace_cli.doc_sync.facts import (
    CommandFact,
    DriftKind,
    FlagFact,
    InterfaceSnapshot,
)


def test_allowlist_entries_have_reasons():
    assert isinstance(UNDOCUMENTED_COMMANDS, dict)
    assert "hook" in UNDOCUMENTED_COMMANDS  # hidden internal dispatcher
    assert all(isinstance(v, str) and v for v in UNDOCUMENTED_COMMANDS.values())


def _write_doc(dirpath: Path, cmd: str, params: str) -> None:
    # NOTE: dedent the template BEFORE interpolating `params`. Interpolating a
    # multi-line `params` (whose continuation lines start at column 0) defeats
    # textwrap.dedent's common-prefix detection, leaving the whole doc indented
    # so it would not start with "---".
    template = textwrap.dedent(
        """\
        ---
        name: brainpalace-{cmd}
        command: {cmd}
        description: x
        parameters:
        {params}
        ---
        # {cmd}
        """
    )
    (dirpath / f"brainpalace-{cmd}.md").write_text(
        template.format(cmd=cmd, params=params)
    )


def _snap(*cmds: CommandFact) -> InterfaceSnapshot:
    return InterfaceSnapshot(
        schema_version=1, source_version="9.9.9", commands=list(cmds)
    )


def test_missing_doc_for_live_command(tmp_path):
    snap = _snap(CommandFact("index", flags=[]))
    chk = CliCommandsChecker(docs_dir=tmp_path)
    recs = chk.check(snap)
    assert any(r.kind is DriftKind.MISSING and r.source_id == "index" for r in recs)


def test_allowlisted_command_not_missing(tmp_path):
    snap = _snap(CommandFact("hook", hidden=True, flags=[]))
    recs = CliCommandsChecker(docs_dir=tmp_path).check(snap)
    assert all(r.source_id != "hook" for r in recs)


def test_extra_doc_for_dead_command(tmp_path):
    _write_doc(
        tmp_path,
        "ghost",
        "  - name: x\n    type: bool\n    required: false\n    default: false",
    )
    recs = CliCommandsChecker(docs_dir=tmp_path).check(_snap())
    assert any(r.kind is DriftKind.EXTRA and r.source_id == "ghost" for r in recs)


def test_flag_mismatch_detected(tmp_path):
    _write_doc(
        tmp_path,
        "index",
        "  - name: force\n    type: bool\n    required: false\n    default: true",
    )
    snap = _snap(
        CommandFact("index", flags=[FlagFact("force", "bool", False, False, "")])
    )
    recs = CliCommandsChecker(docs_dir=tmp_path).check(snap)
    assert any(r.kind is DriftKind.MISMATCH and r.source_id == "index" for r in recs)


def test_clean_when_contract_matches(tmp_path):
    _write_doc(
        tmp_path,
        "index",
        "  - name: force\n    type: bool\n    required: false\n    default: false",
    )
    snap = _snap(
        CommandFact("index", flags=[FlagFact("force", "bool", False, False, "")])
    )
    recs = CliCommandsChecker(docs_dir=tmp_path).check(snap)
    assert recs == []


def test_plugin_only_doc_not_flagged_extra(tmp_path):
    # A plugin slash-command doc (e.g. brainpalace-setup.md) has no matching CLI
    # command; it must not be reported as EXTRA drift nor contract-gated.
    from brainpalace_cli.doc_sync.allowlist import PLUGIN_ONLY_COMMAND_DOCS

    assert "setup" in PLUGIN_ONLY_COMMAND_DOCS  # declared, with a reason
    assert all(isinstance(v, str) and v for v in PLUGIN_ONLY_COMMAND_DOCS.values())

    (tmp_path / "brainpalace-setup.md").write_text(
        "---\nname: brainpalace-setup\nagent: setup-assistant\nparameters: []\n---\n"
        "# Setup\nRun `brainpalace index ./docs` after setup.\n"
    )
    recs = CliCommandsChecker(docs_dir=tmp_path).check(_snap())
    assert all(r.source_id != "setup" for r in recs)  # not EXTRA, not gated


def test_body_flags_block_drift_detected(tmp_path):
    (tmp_path / "brainpalace-index.md").write_text(
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
        ### Flags
        <!--GENERATED:flags-->
        | Flag | Type | Default | Description |
        |------|------|---------|-------------|
        | --STALE | bool | false | wrong |
        <!--/GENERATED-->
        """
        )
    )
    snap = _snap(
        CommandFact("index", flags=[FlagFact("force", "bool", False, False, "")])
    )
    recs = CliCommandsChecker(docs_dir=tmp_path).check(snap)
    assert any(r.kind is DriftKind.MISMATCH and "flags block" in r.detail for r in recs)

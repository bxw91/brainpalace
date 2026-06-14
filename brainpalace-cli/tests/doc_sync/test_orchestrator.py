import textwrap

from brainpalace_cli.doc_sync.checkers.cli_commands import CliCommandsChecker
from brainpalace_cli.doc_sync.facts import CommandFact, FlagFact, InterfaceSnapshot
from brainpalace_cli.doc_sync.orchestrator import run_check, run_fix


def _snap(*c):
    return InterfaceSnapshot(1, "9.9.9", list(c))


def _doc(tmp_path, cmd, params):
    # dedent the template BEFORE interpolating `params` (see test_cli_commands_checker)
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
        ## Purpose
        prose
        """
    )
    (tmp_path / f"brainpalace-{cmd}.md").write_text(
        template.format(cmd=cmd, params=params)
    )


def test_run_check_returns_drift_and_nonzero(tmp_path):
    snap = _snap(
        CommandFact("index", flags=[FlagFact("force", "bool", False, False, "")])
    )
    chk = CliCommandsChecker(docs_dir=tmp_path)
    code, records = run_check([chk], snap)
    assert code == 1 and any(r.source_id == "index" for r in records)  # missing doc


def test_run_fix_regenerates_then_clean(tmp_path):
    _doc(
        tmp_path,
        "index",
        "  - name: stale\n    type: bool\n    required: false\n    default: false",
    )
    snap = _snap(
        CommandFact("index", flags=[FlagFact("force", "bool", False, False, "")])
    )
    chk = CliCommandsChecker(docs_dir=tmp_path)
    prose_needed = run_fix([chk], snap)
    code, records = run_check([chk], snap)
    assert code == 0 and records == []  # contract now matches after regen
    assert isinstance(prose_needed, list)  # no missing prose here

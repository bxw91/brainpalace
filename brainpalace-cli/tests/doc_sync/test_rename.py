import subprocess
import textwrap

from brainpalace_cli.doc_sync.checkers.cli_commands import CliCommandsChecker
from brainpalace_cli.doc_sync.facts import CommandFact, DriftKind, InterfaceSnapshot
from brainpalace_cli.doc_sync.generator import apply_rename


def _doc(d, name):
    (d / f"brainpalace-{name}.md").write_text(
        textwrap.dedent(
            f"""\
        ---
        name: brainpalace-{name}
        description: x
        parameters: []
        ---
        # {name}
        ## Purpose
        prose
        """
        )
    )


def _snap(*names):
    return InterfaceSnapshot(
        1, "9.9.9", commands=[CommandFact(n, flags=[]) for n in names], modes=[]
    )


def test_single_orphan_and_new_emits_rename(tmp_path):
    _doc(tmp_path, "foo")  # orphan doc (foo not live)
    recs = CliCommandsChecker(docs_dir=tmp_path).check(_snap("bar"))  # bar live, no doc
    rn = [r for r in recs if r.kind is DriftKind.RENAME]
    assert len(rn) == 1 and "foo" in rn[0].detail and "bar" in rn[0].detail


def test_two_orphans_no_rename_guess(tmp_path):
    _doc(tmp_path, "foo")
    _doc(tmp_path, "baz")
    recs = CliCommandsChecker(docs_dir=tmp_path).check(_snap("bar"))
    assert not any(r.kind is DriftKind.RENAME for r in recs)
    assert any(r.kind is DriftKind.MISSING and r.source_id == "bar" for r in recs)
    assert {r.source_id for r in recs if r.kind is DriftKind.EXTRA} == {"foo", "baz"}


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_apply_rename_git_mv_preserves_prose_and_consumes_hint(tmp_path):
    _git("init", cwd=tmp_path)
    d = tmp_path
    (d / "brainpalace-foo.md").write_text(
        "---\nname: brainpalace-foo\nparameters: []\n---\n"
        "# foo\n## Purpose\nVALUABLE PROSE\n"
    )
    # stub new doc carrying the confirm hint
    (d / "brainpalace-bar.md").write_text(
        "---\nname: brainpalace-bar\nrenamed_from: foo\n---\n"
    )
    _git("add", "-A", cwd=tmp_path)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "x", cwd=tmp_path)

    moved = apply_rename(d, old="foo", new="bar")
    assert moved is True
    bar = (d / "brainpalace-bar.md").read_text()
    assert "VALUABLE PROSE" in bar  # prose carried over
    assert "name: brainpalace-bar" in bar  # name updated
    assert "renamed_from" not in bar  # hint consumed
    assert not (d / "brainpalace-foo.md").exists()


def test_apply_rename_noop_without_hint(tmp_path):
    _git("init", cwd=tmp_path)
    (tmp_path / "brainpalace-foo.md").write_text(
        "---\nname: brainpalace-foo\n---\n# foo\n"
    )
    assert apply_rename(tmp_path, old="foo", new="bar") is False
    assert (tmp_path / "brainpalace-foo.md").exists()  # untouched

import textwrap

from brainpalace_cli.doc_sync.checkers.cli_commands import referential_drift


def test_flags_dangling_brainpalace_invocation(tmp_path):
    doc = tmp_path / "brainpalace-x.md"
    doc.write_text(
        textwrap.dedent(
            """\
        # X
        ```
        brainpalace test-embedding  # removed command
        brainpalace index ./docs    # valid
        ```
        Some prose mentioning `brainpalace test-summarize` too.
        """
        )
    )
    live_commands = {"index", "query", "status"}
    recs = referential_drift([doc], live_commands)
    bad = {r.source_id for r in recs}
    assert "test-embedding" in bad  # removed command, command position
    assert "test-summarize" in bad  # inline-code span counts as invocation
    assert "index" not in bad  # valid command not flagged


def test_unrelated_shell_not_flagged(tmp_path):
    doc = tmp_path / "brainpalace-x.md"
    doc.write_text("```\nls -la && git status\n```\n")
    recs = referential_drift([doc], {"index"})
    assert recs == []  # only `brainpalace …` invocations are scanned


def test_arg_or_prose_mention_not_an_invocation(tmp_path):
    # `brainpalace` as an env-name arg or a prose word is NOT a command invocation.
    doc = tmp_path / "brainpalace-x.md"
    doc.write_text(
        "```bash\n"
        "conda create -n brainpalace python=3.12 -y\n"
        'echo "Using brainpalace at: $BP_BIN"\n'
        "```\n"
    )
    recs = referential_drift([doc], {"index"})
    assert recs == []  # 'python' / 'at' are not dangling subcommands

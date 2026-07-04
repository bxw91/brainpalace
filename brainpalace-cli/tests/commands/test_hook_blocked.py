"""SessionStart hook appends the AskUserQuestion directive when blocked."""

from brainpalace_cli.commands import hook as hook_mod


def test_blocked_directive_mentions_card_and_command() -> None:
    directive = hook_mod._BLOCKED_JOB_DIRECTIVE.format(job_id="job_1")
    assert "AskUserQuestion" in directive
    assert "brainpalace jobs job_1 --approve" in directive
    assert "non-interactive" in directive.lower()
    # money rule: never auto-approve
    assert "never approve" in directive.lower()


def test_session_context_data_fail_soft(monkeypatch) -> None:
    class _Boom:
        def __init__(self, *a, **k):  # noqa: ANN002, ANN003
            raise ConnectionError("down")

    monkeypatch.setattr("brainpalace_cli.client.DocServeClient", _Boom)
    assert hook_mod._session_context_data("http://127.0.0.1:1") == {}

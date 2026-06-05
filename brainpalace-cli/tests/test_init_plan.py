"""Resolution matrix + rendering for `brainpalace init` planning."""

from brainpalace_cli.commands.init_plan import (
    _provider_label,
    _trim_model_id,
    downgrade_to_config_only,
    format_init_plan,
    resolve_init_plan,
)


def _resolve(**kw):
    base = {
        "start": None,
        "watch": None,
        "no_watch": False,
        "sessions": None,
        "archive": None,
        "extract": None,
        "git_history": None,
        "yes": False,
        "is_tty": False,
    }
    base.update(kw)
    return resolve_init_plan(**base)


class TestResolveGitHistory:
    def test_git_history_defaults_off_even_with_yes(self) -> None:
        assert _resolve(yes=True).git_history is False

    def test_git_history_defaults_off_in_tty(self) -> None:
        assert _resolve(is_tty=True).git_history is False

    def test_git_history_explicit_flag_wins(self) -> None:
        assert _resolve(git_history=True).git_history is True
        assert _resolve(git_history=False, yes=True).git_history is False

    def test_downgrade_clears_git_history(self) -> None:
        full = _resolve(is_tty=True, git_history=True)
        assert downgrade_to_config_only(full).git_history is False

    def test_format_includes_git_history_when_on(self) -> None:
        out = format_init_plan(
            _resolve(yes=True, git_history=True),
            embedding=("openai", "text-embedding-3-large"),
            summarize=None,
        )
        assert "index git history" in out


class TestResolveStartWatch:
    def test_no_tty_no_yes_is_config_only(self) -> None:
        p = _resolve()
        assert p.start is False
        assert p.watch == "off"
        assert p.sessions is False
        assert p.archive is True
        assert p.confirm is False
        assert p.billable is False

    def test_tty_bare_is_full_with_confirm(self) -> None:
        p = _resolve(is_tty=True)
        assert p.start is True
        assert p.watch == "auto"
        assert p.sessions is False  # embedding is opt-in (asked via prompt)
        assert p.archive is True
        assert p.confirm is True
        assert p.billable is True  # docs still embedded (watch=auto)

    def test_yes_is_full_without_confirm(self) -> None:
        p = _resolve(yes=True)
        assert p.start is True
        assert p.watch == "auto"
        assert p.sessions is False  # --yes no longer auto-embeds sessions
        assert p.confirm is False
        assert p.billable is True  # docs still embedded (watch=auto)

    def test_yes_in_tty_does_not_confirm(self) -> None:
        assert _resolve(yes=True, is_tty=True).confirm is False

    def test_explicit_no_start_wins_over_tty(self) -> None:
        p = _resolve(is_tty=True, start=False)
        assert p.start is False
        assert p.watch == "off"  # watch is off when not starting

    def test_explicit_start_in_ci_honored(self) -> None:
        # no TTY, no --yes, but explicit --start: start, watch stays off (implicit)
        p = _resolve(start=True)
        assert p.start is True
        assert p.watch == "off"

    def test_explicit_start_with_watch_value(self) -> None:
        p = _resolve(start=True, watch="auto")
        assert p.start is True
        assert p.watch == "auto"

    def test_no_watch_forces_off_in_tty(self) -> None:
        p = _resolve(is_tty=True, no_watch=True)
        assert p.start is True
        assert p.watch == "off"


class TestResolveSessionsArchive:
    def test_explicit_no_sessions_wins_in_tty(self) -> None:
        p = _resolve(is_tty=True, sessions=False)
        assert p.sessions is False

    def test_explicit_sessions_in_ci(self) -> None:
        p = _resolve(sessions=True)
        assert p.sessions is True

    def test_explicit_no_archive_wins(self) -> None:
        p = _resolve(is_tty=True, archive=False)
        assert p.archive is False

    def test_archive_default_on_even_in_ci(self) -> None:
        assert _resolve().archive is True


class TestDowngrade:
    def test_downgrade_keeps_archive_drops_rest(self) -> None:
        full = _resolve(is_tty=True)
        d = downgrade_to_config_only(full)
        assert d.start is False
        assert d.watch == "off"
        assert d.sessions is False
        assert d.archive is True
        assert d.confirm is False
        assert d.billable is False


class TestTagHelpers:
    def test_trim_strips_date_suffix(self) -> None:
        assert _trim_model_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5"
        assert _trim_model_id("text-embedding-3-large") == "text-embedding-3-large"
        assert _trim_model_id("gpt-5-mini") == "gpt-5-mini"

    def test_provider_label_known_and_unknown(self) -> None:
        assert _provider_label("openai") == "OpenAI"
        assert _provider_label("anthropic") == "Anthropic"
        assert _provider_label("cohere") == "Cohere"
        assert _provider_label("acme") == "Acme"


class TestFormat:
    def test_full_plan_subagent_summarization(self) -> None:
        out = format_init_plan(
            _resolve(yes=True, sessions=True),  # embedding opt-in → set explicitly
            embedding=("openai", "text-embedding-3-large"),
            summarize=("subagent",),
        )
        assert "· index docs (watch=auto)" in out
        assert "→ OpenAI text-embedding-3-large" in out
        assert "· back up chat sessions" in out
        # backup line carries no provider tag
        backup_line = [ln for ln in out.splitlines() if "back up chat sessions" in ln][
            0
        ]
        assert "→" not in backup_line
        assert "· embed chat sessions" in out
        assert "→ Claude Code Haiku (subscription)" in out
        # no abstract cost words
        assert "billable" not in out and "free" not in out
        # jargon dropped
        assert "transcripts" not in out

    def test_provider_summarization_api_usage(self) -> None:
        out = format_init_plan(
            _resolve(yes=True),
            embedding=("openai", "text-embedding-3-large"),
            summarize=("provider", "anthropic", "claude-haiku-4-5-20251001"),
        )
        assert "→ Anthropic claude-haiku-4-5 (API usage)" in out

    def test_summarize_omitted_when_none(self) -> None:
        out = format_init_plan(
            _resolve(yes=True),
            embedding=("openai", "text-embedding-3-large"),
            summarize=None,  # decision 1: plugin absent ⇒ no summarization
        )
        assert "summarize chat sessions" not in out

    def test_no_sessions_drops_embed_chat_line(self) -> None:
        out = format_init_plan(
            _resolve(yes=True, sessions=False),
            embedding=("openai", "text-embedding-3-large"),
            summarize=None,
        )
        assert "embed chat sessions" not in out
        assert "· back up chat sessions" in out  # archive still happens
        assert "index docs (watch=auto)" in out  # docs still embedded

    def test_config_only_plan(self) -> None:
        # archive defaults on, so a truly empty plan needs --no-archive too.
        out = format_init_plan(_resolve(archive=False), embedding=None, summarize=None)
        assert "write config only" in out
        assert "billable" not in out

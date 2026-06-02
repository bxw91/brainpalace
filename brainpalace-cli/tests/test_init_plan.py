"""Resolution matrix + rendering for `brainpalace init` planning."""

from brainpalace_cli.commands.init_plan import (
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
        "yes": False,
        "is_tty": False,
    }
    base.update(kw)
    return resolve_init_plan(**base)


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
        assert p.sessions is True
        assert p.archive is True
        assert p.confirm is True
        assert p.billable is True

    def test_yes_is_full_without_confirm(self) -> None:
        p = _resolve(yes=True)
        assert p.start is True
        assert p.watch == "auto"
        assert p.sessions is True
        assert p.confirm is False
        assert p.billable is True

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


class TestFormat:
    def test_full_plan_lists_all_and_billable(self) -> None:
        line = format_init_plan(_resolve(yes=True))
        assert "start server" in line
        assert "index docs (watch=auto)" in line
        assert "archive transcripts" in line
        assert "embed transcripts" in line
        assert "billable" in line
        assert "document" in line and "transcript" in line

    def test_no_sessions_plan_keeps_archive_drops_transcript_billable(self) -> None:
        line = format_init_plan(_resolve(yes=True, sessions=False))
        assert "embed transcripts" not in line
        assert "archive transcripts" in line  # archive still happens
        assert "transcript embedding" not in line  # transcripts not billed
        assert "document" in line  # doc embed still billable

    def test_config_only_plan(self) -> None:
        # archive defaults on, so a truly empty plan needs --no-archive too.
        line = format_init_plan(_resolve(archive=False))
        assert "write config only" in line
        assert "billable" not in line

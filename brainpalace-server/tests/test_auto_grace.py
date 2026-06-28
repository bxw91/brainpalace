"""Task 4f — auto-grace anchored on subagent activity + cold-start gate."""

from __future__ import annotations

from brainpalace_server.services.auto_grace import (
    provider_auto_eligible,
    read_last_drain,
)


def test_provider_auto_eligible() -> None:
    grace = 24 * 3600
    base = {"server_start_ts": 0.0, "grace_seconds": grace}
    # cold start: no request seen yet → never eligible, even past grace
    assert (
        provider_auto_eligible(
            now=grace + 1, last_drain_ts=None, first_request_seen=False, **base
        )
        is False
    )
    # request seen, no subagent drain, past grace since start → eligible
    assert (
        provider_auto_eligible(
            now=grace + 1, last_drain_ts=None, first_request_seen=True, **base
        )
        is True
    )
    # recent subagent drain → defer (free path active)
    assert (
        provider_auto_eligible(
            now=grace + 1, last_drain_ts=grace - 10, first_request_seen=True, **base
        )
        is False
    )
    # restart resets the window: server_start newer than last_drain
    assert (
        provider_auto_eligible(
            now=grace + 1,
            last_drain_ts=1.0,
            first_request_seen=True,
            server_start_ts=grace,
            grace_seconds=grace,
        )
        is False
    )


def test_read_last_drain(tmp_path) -> None:
    # absent → None
    assert read_last_drain(tmp_path) is None
    # parse error → None
    state = tmp_path / ".brainpalace" / "state"
    state.mkdir(parents=True)
    (state / "last-drain").write_text("not-a-float", encoding="utf-8")
    assert read_last_drain(tmp_path) is None
    # valid float epoch → that value
    (state / "last-drain").write_text("1234.5", encoding="utf-8")
    assert read_last_drain(tmp_path) == 1234.5

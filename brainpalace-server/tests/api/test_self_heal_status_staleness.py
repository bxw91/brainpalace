"""Startup self-heal status must reflect THIS server's boot, not the log's tail.

A healthy startup self-heal records no recovery event (a no-op is silent by
design), so the newest event in the append-only log can predate the running
server by days. Surfacing it unconditionally replayed a long-since-healed
"N chunk(s) need re-embed" that no restart could clear.
"""

from brainpalace_server.api.routers.health import _heal_event_is_current


def test_event_older_than_this_boot_is_not_current():
    # The bug: a healed-days-ago event replayed forever because every healthy
    # boot since recorded nothing to supersede it.
    stale = {"ts": "2026-07-12T20:05:10.474378+00:00", "residue": 19}
    assert _heal_event_is_current(stale, "2026-07-17T03:23:26.000000+00:00") is False


def test_event_from_this_boot_is_current():
    fresh = {"ts": "2026-07-17T03:23:30.000000+00:00", "residue": 4}
    assert _heal_event_is_current(fresh, "2026-07-17T03:23:26.000000+00:00") is True


def test_event_exactly_at_boot_is_current():
    ts = "2026-07-17T03:23:26.000000+00:00"
    assert _heal_event_is_current({"ts": ts}, ts) is True


def test_missing_last_event_is_not_current():
    assert _heal_event_is_current(None, "2026-07-17T03:23:26+00:00") is False


def test_degrades_open_when_timestamps_missing_or_unparseable():
    # A real recovery signal must never be hidden by a clock/format problem.
    started = "2026-07-17T03:23:26+00:00"
    assert _heal_event_is_current({"residue": 19}, started) is True
    assert _heal_event_is_current({"ts": "not-a-date"}, started) is True
    assert _heal_event_is_current({"ts": "2026-07-12T20:05:10+00:00"}, None) is True


def test_naive_and_aware_timestamps_compare_without_raising():
    # Mixed tz-awareness would raise on compare; both sides normalise to UTC.
    assert (
        _heal_event_is_current(
            {"ts": "2026-07-12T20:05:10"}, "2026-07-17T03:23:26+00:00"
        )
        is False
    )
    assert (
        _heal_event_is_current(
            {"ts": "2026-07-17T04:00:00+00:00"}, "2026-07-17T03:23:26"
        )
        is True
    )

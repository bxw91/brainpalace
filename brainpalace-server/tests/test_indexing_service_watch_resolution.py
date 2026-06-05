"""Unit tests for the watch-mode resolution rule (Q1 first-index fix)."""

from brainpalace_server.services.indexing_service import _resolve_watch_settings


def test_explicit_request_wins_on_new_folder():
    mode, debounce = _resolve_watch_settings(
        has_existing=False,
        existing_watch_mode=None,
        existing_debounce=None,
        request_watch_mode="auto",
        request_debounce=30,
    )
    assert mode == "auto"
    assert debounce == 30


def test_new_folder_no_flag_defaults_off():
    mode, debounce = _resolve_watch_settings(
        has_existing=False,
        existing_watch_mode=None,
        existing_debounce=None,
        request_watch_mode=None,
        request_debounce=None,
    )
    assert mode == "off"
    assert debounce is None


def test_no_flag_preserves_existing_auto_on_reindex():
    mode, debounce = _resolve_watch_settings(
        has_existing=True,
        existing_watch_mode="auto",
        existing_debounce=15,
        request_watch_mode=None,
        request_debounce=None,
    )
    assert mode == "auto"
    assert debounce == 15


def test_explicit_flag_upgrades_existing_off_to_auto():
    mode, debounce = _resolve_watch_settings(
        has_existing=True,
        existing_watch_mode="off",
        existing_debounce=None,
        request_watch_mode="auto",
        request_debounce=20,
    )
    assert mode == "auto"
    assert debounce == 20


def test_explicit_off_downgrades_existing_auto():
    mode, debounce = _resolve_watch_settings(
        has_existing=True,
        existing_watch_mode="auto",
        existing_debounce=15,
        request_watch_mode="off",
        request_debounce=None,
    )
    assert mode == "off"
    assert debounce is None

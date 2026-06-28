"""The server surfaces the source-build git ref over HTTP (the /health version
field the dashboard Status tab and `brainpalace status` show) — ``(from <branch>
<short-commit>)``, falling back to ``(from source)`` — when installed from local
source, distinguishing it from a same-numbered PyPI release. Mirrors the CLI's
`--version` and the dashboard footer. The raw ``__version__`` stays pure (no
consumer parses the /health version, but comparisons must keep working).
"""

from __future__ import annotations

import brainpalace_server


def test_direct_url_file_is_source():
    assert brainpalace_server._direct_url_is_file('{"url": "file:///srv"}')


def test_direct_url_registry_is_not_source():
    assert not brainpalace_server._direct_url_is_file('{"url": "https://pypi.org/x"}')


def test_direct_url_missing_is_not_source():
    assert not brainpalace_server._direct_url_is_file(None)


def test_direct_url_garbage_is_not_source():
    assert not brainpalace_server._direct_url_is_file("not json{")


def test_version_display_marks_source_with_git_ref(monkeypatch):
    monkeypatch.setattr(
        brainpalace_server, "_installed_from_source", lambda *a, **k: True
    )
    monkeypatch.setattr(
        brainpalace_server, "_source_git_ref", lambda *a, **k: "stable a8499295"
    )
    assert (
        brainpalace_server.version_display()
        == f"{brainpalace_server.__version__} (from stable a8499295)"
    )


def test_version_display_falls_back_to_source_without_git(monkeypatch):
    monkeypatch.setattr(
        brainpalace_server, "_installed_from_source", lambda *a, **k: True
    )
    monkeypatch.setattr(brainpalace_server, "_source_git_ref", lambda *a, **k: None)
    assert (
        brainpalace_server.version_display()
        == f"{brainpalace_server.__version__} (from source)"
    )


def test_version_display_plain_for_release(monkeypatch):
    monkeypatch.setattr(
        brainpalace_server, "_installed_from_source", lambda *a, **k: False
    )
    assert brainpalace_server.version_display() == brainpalace_server.__version__

"""`--version` distinguishes a local source build from a same-numbered PyPI
release. The version NUMBER can't (it's the static pyproject value), so we read
PEP 610 install provenance (`direct_url.json`): a `file://` URL means the package
was installed from a local path (dev-install / editable). For such builds we append
the git ref of the source checkout — " (from <branch> <short-commit>)" — falling
back to " (from source)" when git info is unavailable. A released wheel has no such
record → plain number.
"""

from __future__ import annotations

import brainpalace_cli


def test_direct_url_file_is_source():
    assert brainpalace_cli._direct_url_is_file('{"url": "file:///home/u/brainpalace"}')


def test_direct_url_registry_is_not_source():
    assert not brainpalace_cli._direct_url_is_file('{"url": "https://pypi.org/x"}')


def test_direct_url_missing_is_not_source():
    assert not brainpalace_cli._direct_url_is_file(None)


def test_direct_url_garbage_is_not_source():
    assert not brainpalace_cli._direct_url_is_file("not json{")


def test_version_display_appends_git_ref_for_source(monkeypatch):
    monkeypatch.setattr(brainpalace_cli, "_installed_from_source", lambda *a, **k: True)
    monkeypatch.setattr(
        brainpalace_cli, "_source_git_ref", lambda *a, **k: "stable a8499295"
    )
    assert (
        brainpalace_cli.version_display()
        == f"{brainpalace_cli.__version__} (from stable a8499295)"
    )


def test_version_display_falls_back_to_source_without_git(monkeypatch):
    monkeypatch.setattr(brainpalace_cli, "_installed_from_source", lambda *a, **k: True)
    monkeypatch.setattr(brainpalace_cli, "_source_git_ref", lambda *a, **k: None)
    assert (
        brainpalace_cli.version_display()
        == f"{brainpalace_cli.__version__} (from source)"
    )


def test_version_display_plain_for_release(monkeypatch):
    monkeypatch.setattr(
        brainpalace_cli, "_installed_from_source", lambda *a, **k: False
    )
    assert brainpalace_cli.version_display() == brainpalace_cli.__version__

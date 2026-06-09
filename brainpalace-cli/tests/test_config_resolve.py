"""Per-key config resolution + sparse unset (project < global < code)."""

from __future__ import annotations

from brainpalace_cli.config_resolve import (
    inherited,
    resolve,
    unset_dotpath,
)


def test_resolve_project_wins():
    proj = {"bm25": {"language": "hr"}}
    glob = {"bm25": {"language": "de"}}
    assert resolve("bm25.language", proj, glob) == ("hr", "project")


def test_resolve_falls_through_to_global():
    proj: dict = {}
    glob = {"bm25": {"language": "de"}}
    assert resolve("bm25.language", proj, glob) == ("de", "global")


def test_resolve_falls_through_to_code_default():
    assert resolve("bm25.language", {}, {}) == ("en", "code")


def test_resolve_unset_unknown_key():
    assert resolve("nope.nothere", {}, {}) == (None, "unset")


def test_inherited_skips_project_layer():
    glob = {"bm25": {"language": "de"}}
    assert inherited("bm25.language", glob) == ("de", "global")
    assert inherited("bm25.language", {}) == ("en", "code")


def test_unset_removes_key_and_prunes_empty_parent():
    cfg = {"bm25": {"language": "hr"}, "embedding": {"provider": "openai"}}
    assert unset_dotpath(cfg, "bm25.language") is True
    assert cfg == {"embedding": {"provider": "openai"}}  # bm25 pruned


def test_unset_keeps_nonempty_parent():
    cfg = {"bm25": {"language": "hr", "engine": "stem"}}
    assert unset_dotpath(cfg, "bm25.language") is True
    assert cfg == {"bm25": {"engine": "stem"}}


def test_unset_missing_key_is_noop():
    cfg = {"bm25": {"engine": "stem"}}
    assert unset_dotpath(cfg, "bm25.language") is False
    assert cfg == {"bm25": {"engine": "stem"}}

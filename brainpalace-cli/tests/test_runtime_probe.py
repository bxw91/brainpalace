"""Unit tests for the identity-checked health probe (Part A, DA1-DA4).

See ``.planning/specs/2026-07-13-identity-checked-server-health.md``.
"""

from __future__ import annotations

from brainpalace_cli import runtime_probe as probe_mod


def test_probe_mine_when_root_matches(tmp_path, monkeypatch):
    """200 + matching (realpath) project_root => "mine"."""
    monkeypatch.setattr(
        probe_mod,
        "fetch_health_body",
        lambda url, timeout=3.0: {"project_root": str(tmp_path)},
    )
    assert probe_mod.probe("http://127.0.0.1:8000", tmp_path) == "mine"


def test_probe_other_when_root_differs(tmp_path, monkeypatch):
    """200 + a DIFFERENT project_root => "other" (not this project's server)."""
    other_root = tmp_path / "other-project"
    other_root.mkdir()
    monkeypatch.setattr(
        probe_mod,
        "fetch_health_body",
        lambda url, timeout=3.0: {"project_root": str(other_root)},
    )
    mine_root = tmp_path / "mine"
    mine_root.mkdir()
    assert probe_mod.probe("http://127.0.0.1:8000", mine_root) == "other"


def test_probe_mine_when_project_root_none(tmp_path, monkeypatch):
    """200 + project_root None/absent (global mode) => "mine" (DA3 fallback,
    preserves the anti-duplicate guard rather than disproving ownership)."""
    monkeypatch.setattr(
        probe_mod,
        "fetch_health_body",
        lambda url, timeout=3.0: {"project_root": None},
    )
    assert probe_mod.probe("http://127.0.0.1:8000", tmp_path) == "mine"


def test_probe_mine_when_project_root_key_absent(tmp_path, monkeypatch):
    """Same as above but the key is entirely missing from the payload."""
    monkeypatch.setattr(
        probe_mod, "fetch_health_body", lambda url, timeout=3.0: {"status": "healthy"}
    )
    assert probe_mod.probe("http://127.0.0.1:8000", tmp_path) == "mine"


def test_probe_down_when_unreachable(tmp_path, monkeypatch):
    """Unreachable / non-200 => "down"."""
    monkeypatch.setattr(probe_mod, "fetch_health_body", lambda url, timeout=3.0: None)
    assert probe_mod.probe("http://127.0.0.1:8000", tmp_path) == "down"


def test_probe_realpath_both_sides(tmp_path, monkeypatch):
    """DA4: symlinked/normalized expected_root must still resolve to "mine"."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    link_dir.symlink_to(real_dir)
    monkeypatch.setattr(
        probe_mod,
        "fetch_health_body",
        lambda url, timeout=3.0: {"project_root": str(real_dir)},
    )
    # Ask with the symlinked path; probe must realpath() it before comparing.
    assert probe_mod.probe("http://127.0.0.1:8000", link_dir) == "mine"


def test_check_health_true_when_reachable(monkeypatch):
    monkeypatch.setattr(
        probe_mod, "fetch_health_body", lambda url, timeout=3.0: {"status": "healthy"}
    )
    assert probe_mod.check_health("http://127.0.0.1:8000") is True


def test_check_health_false_when_unreachable(monkeypatch):
    monkeypatch.setattr(probe_mod, "fetch_health_body", lambda url, timeout=3.0: None)
    assert probe_mod.check_health("http://127.0.0.1:8000") is False

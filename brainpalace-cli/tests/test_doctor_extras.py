from unittest.mock import patch

from brainpalace_cli import optional_deps as od
from brainpalace_cli.commands.doctor import extras_status_lines


def test_enabled_missing_extra_reports_fix():
    """bm25.engine=lemma still needs the lemma-hr extra — reports missing."""
    cfg = {"bm25": {"engine": "lemma"}}
    with patch("brainpalace_cli.optional_deps.is_installed", return_value=False):
        lines = extras_status_lines(cfg)
    assert any("lemma-hr" in ln and "missing" in ln.lower() for ln in lines)


def test_enabled_installed_extra_reports_installed():
    """bm25.engine=lemma with extra installed reports installed."""
    cfg = {"bm25": {"engine": "lemma"}}
    with patch("brainpalace_cli.optional_deps.is_installed", return_value=True):
        lines = extras_status_lines(cfg)
    assert any("lemma-hr" in ln and "installed" in ln.lower() for ln in lines)


def test_declined_feature_not_reported():
    """extraction.mode=subagent has no extra dep; no extras lines emitted."""
    cfg = {"extraction": {"mode": "subagent"}}
    with patch("brainpalace_cli.optional_deps.is_installed", return_value=False):
        lines = extras_status_lines(cfg)
    assert lines == []


def test_manual_install_hint_pipx():
    with (
        patch.object(od, "detect_install_manager", return_value="pipx"),
        patch.object(od, "_installed_rag_version", return_value="1.2.3"),
    ):
        hint = od.manual_install_hint("graphrag")
    assert "pipx" in hint
    assert "brainpalace-rag[graphrag]==1.2.3" in hint
    assert "\n" not in hint


def test_manual_install_hint_uv():
    with (
        patch.object(od, "detect_install_manager", return_value="uv"),
        patch.object(od, "_installed_rag_version", return_value=None),
    ):
        hint = od.manual_install_hint("postgres")
    assert hint.startswith("uv ")
    assert "brainpalace-rag[postgres]" in hint
    assert "\n" not in hint


def test_manual_install_hint_no_manager_falls_back():
    with (
        patch.object(od, "detect_install_manager", return_value=None),
        patch.object(od, "_installed_rag_version", return_value=None),
    ):
        hint = od.manual_install_hint("lemma-hr")
    assert "pipx inject" in hint
    assert "pip install" in hint
    assert "\n" not in hint

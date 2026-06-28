from unittest.mock import patch

import pytest

from brainpalace_cli import optional_deps as od


def test_registry_extras():
    assert set(od.REGISTRY) == {
        "lemma-hr",
        "postgres",
        "reranker-local",
    }
    assert od.REGISTRY["reranker-local"].probe_module == "sentence_transformers"


@pytest.mark.parametrize(
    "manager,expected_head",
    [
        ("pipx", ["pipx", "inject", "brainpalace-cli"]),
        ("uv", ["uv", "tool", "install", "brainpalace-cli", "--with"]),
        ("pip", ["/usr/bin/python", "-m", "pip", "install"]),
    ],
)
def test_install_argv_shapes(manager, expected_head, monkeypatch):
    monkeypatch.setattr(od.sys, "executable", "/usr/bin/python")
    argv = od.install_argv("lemma-hr", manager, "26.6.33")
    assert argv[: len(expected_head)] == expected_head
    assert any("brainpalace-rag[lemma-hr]==26.6.33" in a for a in argv)
    assert any("no-cache" in a for a in argv)


def test_install_argv_unknown_manager_returns_none():
    assert od.install_argv("lemma-hr", "conda", "1.0") is None


def test_ensure_extra_noop_when_already_installed():
    with (
        patch.object(od, "is_installed", return_value=True),
        patch.object(od.subprocess, "run") as run,
    ):
        res = od.ensure_extra("lemma-hr", assume_yes=True)
    assert res.installed is True
    run.assert_not_called()


def test_ensure_extra_prints_when_manager_undetected(capsys):
    with (
        patch.object(od, "is_installed", return_value=False),
        patch.object(od, "detect_install_manager", return_value=None),
        patch.object(od.subprocess, "run") as run,
    ):
        res = od.ensure_extra("lemma-hr", assume_yes=True)
    out = capsys.readouterr().out
    assert res.installed is False
    assert res.printed is True
    run.assert_not_called()
    assert "brainpalace-rag[lemma-hr]" in out


def test_ensure_extra_runs_when_detected_then_reports_installed():
    class _OK:
        returncode = 0

    with (
        patch.object(od, "is_installed", side_effect=[False, True]),
        patch.object(od, "detect_install_manager", return_value="pip"),
        patch.object(od, "_installed_rag_version", return_value="26.6.33"),
        patch.object(od.subprocess, "run", return_value=_OK()) as run,
    ):
        res = od.ensure_extra("lemma-hr", assume_yes=True)
    assert res.installed is True
    run.assert_called_once()


def test_ensure_extra_run_failure_prints_command(capsys):
    class _Fail:
        returncode = 1

    with (
        patch.object(od, "is_installed", return_value=False),
        patch.object(od, "detect_install_manager", return_value="pip"),
        patch.object(od, "_installed_rag_version", return_value="26.6.33"),
        patch.object(od.subprocess, "run", return_value=_Fail()),
    ):
        res = od.ensure_extra("lemma-hr", assume_yes=True)
    out = capsys.readouterr().out
    assert res.installed is False
    assert res.printed is True
    assert "brainpalace-rag[lemma-hr]" in out

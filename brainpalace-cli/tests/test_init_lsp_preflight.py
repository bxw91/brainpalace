"""Task 6 — `init` preflight offers (never auto-installs) a missing LSP server."""

import brainpalace_cli.commands.init as initmod
from brainpalace_cli.lsp_install import EnsureResult


def test_preflight_lsp_interactive_prompts_never_assume_yes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        initmod, "_lsp_missing_languages", lambda sd: ["python"], raising=False
    )
    seen = {}

    def _ensure(lang, *, assume_yes, interactive):
        seen["lang"] = lang
        seen["assume_yes"] = assume_yes
        return EnsureResult.INSTALLED

    monkeypatch.setattr(initmod, "ensure_server", _ensure, raising=False)
    initmod._preflight_lsp(tmp_path, interactive=True, json_output=False)
    assert seen["lang"] == "python"
    # H4: init must NEVER auto-install — always assume_yes=False.
    assert seen["assume_yes"] is False


def test_preflight_lsp_noninteractive_nudges_not_installs(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        initmod, "_lsp_missing_languages", lambda sd: ["python"], raising=False
    )
    called = {"n": 0}

    def _ensure(lang, **k):
        called["n"] += 1
        return EnsureResult.DECLINED

    monkeypatch.setattr(initmod, "ensure_server", _ensure, raising=False)
    initmod._preflight_lsp(tmp_path, interactive=False, json_output=False)
    # Non-interactive: nudge, do NOT invoke the installer.
    assert called["n"] == 0
    assert "lsp install" in capsys.readouterr().out


def test_preflight_lsp_json_is_silent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        initmod, "_lsp_missing_languages", lambda sd: ["python"], raising=False
    )
    monkeypatch.setattr(
        initmod, "ensure_server", lambda *a, **k: EnsureResult.DECLINED, raising=False
    )
    initmod._preflight_lsp(tmp_path, interactive=False, json_output=True)
    assert capsys.readouterr().out == ""

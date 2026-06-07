"""`brainpalace start` auto-starts the web dashboard and reports its URL.

Covers the best-effort `_ensure_dashboard` helper (opt-out, missing package,
autostart config, failure swallowing) and the wiring into the start command's
human + --json output. The dashboard package is faked via sys.modules so these
tests are deterministic regardless of the interpreter's real dashboard install.
"""

from __future__ import annotations

import json
import os
import sys
import types

from click.testing import CliRunner

import brainpalace_cli.commands.start as start_mod


def _install_fake_dashboard(
    monkeypatch, *, autostart=True, ensure_result=None, ensure_raises=None
) -> dict:
    """Register fake brainpalace_dashboard modules; return a calls-capture dict."""
    calls: dict[str, object] = {}

    cfg_mod = types.ModuleType("brainpalace_dashboard.config")
    _cfg = types.SimpleNamespace(autostart=autostart)
    cfg_mod.load_dashboard_config = lambda: _cfg  # type: ignore[attr-defined]

    srv_mod = types.ModuleType("brainpalace_dashboard.server")

    def _ensure_running(*, open_browser_if_new=False, **_kw):
        calls["open_browser_if_new"] = open_browser_if_new
        if ensure_raises is not None:
            raise ensure_raises
        return ensure_result

    srv_mod.ensure_running = _ensure_running  # type: ignore[attr-defined]

    pkg = types.ModuleType("brainpalace_dashboard")
    pkg.server = srv_mod  # type: ignore[attr-defined]
    pkg.config = cfg_mod  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "brainpalace_dashboard", pkg)
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard.server", srv_mod)
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard.config", cfg_mod)
    return calls


# --------------------------------------------------------------------------- #
# _ensure_dashboard helper
# --------------------------------------------------------------------------- #
def test_ensure_dashboard_skips_when_flag_set(monkeypatch):
    # --no-dashboard wins even if the package would be importable.
    _install_fake_dashboard(monkeypatch, ensure_result={"base_url": "x"})
    assert start_mod._ensure_dashboard(no_dashboard=True, json_output=False) is None


def test_ensure_dashboard_silent_when_not_installed(monkeypatch):
    # Simulate Python 3.10/3.11 (dashboard extra absent): import raises.
    monkeypatch.setitem(sys.modules, "brainpalace_dashboard", None)
    assert start_mod._ensure_dashboard(no_dashboard=False, json_output=False) is None


def test_ensure_dashboard_skips_when_autostart_false(monkeypatch):
    _install_fake_dashboard(
        monkeypatch, autostart=False, ensure_result={"base_url": "x"}
    )
    assert start_mod._ensure_dashboard(no_dashboard=False, json_output=False) is None


def test_ensure_dashboard_returns_info_and_no_browser_in_json(monkeypatch):
    info = {"base_url": "http://127.0.0.1:8787/dashboard/", "started": True}
    calls = _install_fake_dashboard(monkeypatch, ensure_result=info)
    out = start_mod._ensure_dashboard(no_dashboard=False, json_output=True)
    assert out == info
    # --json never opens a browser.
    assert calls["open_browser_if_new"] is False


def test_ensure_dashboard_swallows_failure(monkeypatch):
    _install_fake_dashboard(monkeypatch, ensure_raises=RuntimeError("boom"))
    # A dashboard failure must never propagate out of `brainpalace start`.
    assert start_mod._ensure_dashboard(no_dashboard=False, json_output=False) is None


# --------------------------------------------------------------------------- #
# wiring into the start command
# --------------------------------------------------------------------------- #
def _make_running_project(tmp_path):
    state_dir = tmp_path / ".brainpalace"
    state_dir.mkdir()
    (state_dir / "config.json").write_text(
        json.dumps({"bind_host": "127.0.0.1", "auto_port": True})
    )
    (state_dir / start_mod.RUNTIME_FILE).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "base_url": "http://127.0.0.1:8000",
                "project_root": str(tmp_path),
            }
        )
    )
    (state_dir / start_mod.LOCK_FILE).write_text("")
    return state_dir


def test_start_prints_dashboard_url(tmp_path, monkeypatch):
    _make_running_project(tmp_path)
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)
    monkeypatch.setattr(
        start_mod,
        "_ensure_dashboard",
        lambda **_k: {
            "base_url": "http://127.0.0.1:8787/dashboard/",
            "started": True,
        },
    )

    result = CliRunner().invoke(start_mod.start_command, ["--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "http://127.0.0.1:8787/dashboard/" in result.output


def test_start_json_includes_dashboard(tmp_path, monkeypatch):
    _make_running_project(tmp_path)
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)
    monkeypatch.setattr(
        start_mod,
        "_ensure_dashboard",
        lambda **_k: {
            "base_url": "http://127.0.0.1:8787/dashboard/",
            "started": False,
        },
    )

    result = CliRunner().invoke(
        start_mod.start_command, ["--path", str(tmp_path), "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dashboard"]["base_url"] == "http://127.0.0.1:8787/dashboard/"
    assert payload["dashboard"]["started"] is False


def test_start_no_dashboard_flag_omits_url(tmp_path, monkeypatch):
    _make_running_project(tmp_path)
    monkeypatch.setattr(start_mod, "check_health", lambda url, timeout=3.0: True)
    monkeypatch.setattr(start_mod, "migrate_legacy_paths", lambda: None)

    result = CliRunner().invoke(
        start_mod.start_command, ["--path", str(tmp_path), "--no-dashboard", "--json"]
    )
    assert result.exit_code == 0
    assert "dashboard" not in json.loads(result.output)

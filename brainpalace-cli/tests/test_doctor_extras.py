import json
from pathlib import Path
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


class TestMcpConfigApproval:
    """`doctor` used to call a registered-but-unapproved server OK. That is
    the state a project sits in when Claude Code holds it at 'Pending
    approval': .mcp.json is perfect and the tools never load."""

    @staticmethod
    def _project(tmp_path: Path, settings: dict | None = None) -> Path:
        (tmp_path / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"brainpalace": {"command": "brainpalace"}}})
        )
        if settings is not None:
            local = tmp_path / ".claude" / "settings.local.json"
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(json.dumps(settings))
        return tmp_path

    def test_registered_but_unapproved_warns(self, tmp_path: Path) -> None:
        from brainpalace_cli.diagnostics import _check_mcp_config

        result = _check_mcp_config(self._project(tmp_path), True)
        assert result is not None
        assert result.status != "ok"
        assert "not approved" in result.message

    def test_registered_and_approved_is_ok(self, tmp_path: Path) -> None:
        from brainpalace_cli.diagnostics import _check_mcp_config

        proj = self._project(tmp_path, {"enabledMcpjsonServers": ["brainpalace"]})
        result = _check_mcp_config(proj, True)
        assert result is not None
        assert result.status == "ok"

    def test_explicit_disable_counts_as_unapproved(self, tmp_path: Path) -> None:
        """Denylist wins in Claude Code, so allowlisted+denylisted is denied."""
        from brainpalace_cli.diagnostics import _check_mcp_config

        proj = self._project(
            tmp_path,
            {
                "enabledMcpjsonServers": ["brainpalace"],
                "disabledMcpjsonServers": ["brainpalace"],
            },
        )
        result = _check_mcp_config(proj, True)
        assert result is not None
        assert result.status != "ok"

    def test_local_scope_registration_is_ok_without_allowlist(
        self, tmp_path: Path
    ) -> None:
        """Local scope grants the connection with no approval and no allowlist
        — doctor must call that OK, not warn about a missing approval that the
        local-scope route never needs."""
        from brainpalace_cli.diagnostics import _check_mcp_config

        proj = tmp_path / "proj"
        proj.mkdir()
        self._project(proj)  # .mcp.json only, no settings.local.json
        home = tmp_path / "home"
        home.mkdir()
        (home / ".claude.json").write_text(
            json.dumps({"projects": {str(proj): {"mcpServers": {"brainpalace": {}}}}})
        )
        with patch("brainpalace_cli.diagnostics.Path.home", return_value=home):
            result = _check_mcp_config(proj, True)
        assert result is not None
        assert result.status == "ok"

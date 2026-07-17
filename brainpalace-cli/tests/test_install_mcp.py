"""Tests for ``brainpalace install-mcp`` (spec phase 4c).

Covers the two invariants that ship without which the command is unsafe:
A10 (merge into an existing ``.mcp.json``, never clobber other servers) and
D17 (the restart notice must not assert the tools are unavailable when it
cannot know — the ``already_installed`` path).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from brainpalace_cli.commands.install_mcp import (
    _SERVER_CONFIG,
    _SERVER_KEY,
    install_mcp,
    local_scope_has_server,
    merge_mcp_config,
    register_local_scope,
    restart_notice,
)


class TestMergeNeverClobbers:
    """A10 — the hard blocker: preserve every other declared server."""

    def test_merge_preserves_foreign_servers(self):
        existing = {
            "mcpServers": {
                "context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]},
                "supabase": {"command": "npx", "args": ["-y", "@supabase/mcp"]},
            }
        }
        merged, changed = merge_mcp_config(existing)
        assert changed is True
        assert set(merged["mcpServers"]) == {"context7", "supabase", _SERVER_KEY}
        # foreign entries byte-identical
        assert merged["mcpServers"]["context7"] == existing["mcpServers"]["context7"]
        assert merged["mcpServers"]["supabase"] == existing["mcpServers"]["supabase"]
        assert merged["mcpServers"][_SERVER_KEY] == _SERVER_CONFIG

    def test_merge_is_idempotent(self):
        once, changed1 = merge_mcp_config({})
        assert changed1 is True
        twice, changed2 = merge_mcp_config(once)
        assert changed2 is False
        assert twice == once  # no duplicate, no churn

    def test_merge_does_not_mutate_input(self):
        existing = {"mcpServers": {"context7": {"command": "npx", "args": []}}}
        merge_mcp_config(existing)
        assert _SERVER_KEY not in existing["mcpServers"]  # deepcopy, not in place


class TestInstallOnDisk:
    def test_creates_file_when_absent(self, tmp_path: Path):
        result = install_mcp(tmp_path)
        assert result.changed is True
        written = json.loads((tmp_path / ".mcp.json").read_text())
        assert written["mcpServers"][_SERVER_KEY] == _SERVER_CONFIG

    def test_rerun_leaves_file_unchanged(self, tmp_path: Path):
        install_mcp(tmp_path)
        before = (tmp_path / ".mcp.json").read_text()
        result = install_mcp(tmp_path)
        assert result.changed is False
        assert (tmp_path / ".mcp.json").read_text() == before

    def test_malformed_file_fails_loudly(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text("{ this is not json")
        with pytest.raises(ValueError, match="Could not parse"):
            install_mcp(tmp_path)
        # the malformed file is left untouched, never overwritten
        assert (tmp_path / ".mcp.json").read_text() == "{ this is not json"

    def test_non_object_toplevel_refused(self, tmp_path: Path):
        (tmp_path / ".mcp.json").write_text("[]")
        with pytest.raises(ValueError, match="does not contain a JSON object"):
            install_mcp(tmp_path)


def _settings(root: Path) -> dict:
    return json.loads((root / ".claude" / "settings.local.json").read_text())


class TestApproval:
    """Declaring a server Claude Code then refuses to load is a half-install:
    it sits at 'Pending approval' forever. These pin the approval half."""

    def test_approval_recorded_in_local_settings(self, tmp_path: Path):
        result = install_mcp(tmp_path)
        assert result.approved is True
        assert _settings(tmp_path)["enabledMcpjsonServers"] == [_SERVER_KEY]

    def test_approval_never_enables_all_servers(self, tmp_path: Path):
        """The allowlist approves brainpalace ONLY. enableAllProjectMcpServers
        would approve every server the project declares, now and later."""
        install_mcp(tmp_path)
        assert "enableAllProjectMcpServers" not in _settings(tmp_path)

    def test_approval_preserves_existing_settings(self, tmp_path: Path):
        """settings.local.json holds the user's permissions/hooks — same
        never-clobber discipline as .mcp.json (A10)."""
        settings_path = tmp_path / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["Bash(ls:*)"]},
                    "enabledMcpjsonServers": ["context7"],
                }
            )
        )
        install_mcp(tmp_path)
        after = _settings(tmp_path)
        assert after["permissions"] == {"allow": ["Bash(ls:*)"]}
        assert after["enabledMcpjsonServers"] == ["context7", _SERVER_KEY]

    def test_approval_is_idempotent(self, tmp_path: Path):
        install_mcp(tmp_path)
        install_mcp(tmp_path)
        assert _settings(tmp_path)["enabledMcpjsonServers"] == [_SERVER_KEY]

    def test_rerun_reports_approved_end_state_not_who_wrote_it(self, tmp_path: Path):
        """approved is the END STATE: a re-run must still say 'approved',
        or the notice tells an already-working user to go approve it."""
        install_mcp(tmp_path)
        assert install_mcp(tmp_path).approved is True

    def test_explicit_disable_is_respected(self, tmp_path: Path):
        """Denylist wins in Claude Code, so writing the allowlist over it
        would be inert anyway — and overriding a hand-made choice is not
        this command's call."""
        settings_path = tmp_path / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"disabledMcpjsonServers": [_SERVER_KEY]}))
        result = install_mcp(tmp_path)
        assert result.approved is False
        assert result.skip_reason is not None
        assert _SERVER_KEY not in _settings(tmp_path).get("enabledMcpjsonServers", [])

    def test_no_approve_declares_without_approving(self, tmp_path: Path):
        result = install_mcp(tmp_path, approve=False)
        assert result.changed is True
        assert result.approved is False
        assert not (tmp_path / ".claude" / "settings.local.json").exists()

    def test_malformed_settings_fails_loudly(self, tmp_path: Path):
        """It holds the user's permissions — never silently overwrite it."""
        settings_path = tmp_path / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{ not json")
        with pytest.raises(ValueError, match="Could not parse"):
            install_mcp(tmp_path)
        assert settings_path.read_text() == "{ not json"


class TestLocalScope:
    """The route that needs no approval AND no folder trust, because the
    server lives in the user's own ~/.claude.json rather than the repo."""

    def test_auto_prefers_local_scope_when_claude_present(self, tmp_path: Path):
        with (
            patch(
                "brainpalace_cli.commands.install_mcp.which",
                return_value="/usr/bin/claude",
            ),
            patch("brainpalace_cli.commands.install_mcp.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            result = install_mcp(tmp_path)

        assert result.scope == "local"
        assert result.approved is True
        # local scope grants the connection, so the allowlist is not written
        assert not (tmp_path / ".claude" / "settings.local.json").exists()
        cmd = run.call_args.args[0]
        assert cmd[1:5] == ["mcp", "add", _SERVER_KEY, "-s"]
        assert run.call_args.kwargs["cwd"] == tmp_path

    def test_mcp_json_still_written_in_local_scope(self, tmp_path: Path):
        """.mcp.json stays the shareable declaration; local scope only decides
        how the connection is granted. Local wins over .mcp.json in Claude
        Code, so both together are not a conflict."""
        with (
            patch(
                "brainpalace_cli.commands.install_mcp.which",
                return_value="/usr/bin/claude",
            ),
            patch("brainpalace_cli.commands.install_mcp.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            install_mcp(tmp_path)
        written = json.loads((tmp_path / ".mcp.json").read_text())
        assert written["mcpServers"][_SERVER_KEY] == _SERVER_CONFIG

    def test_auto_falls_back_to_project_without_claude_cli(self, tmp_path: Path):
        """BrainPalace does not depend on Claude Code being installed."""
        result = install_mcp(tmp_path)  # autouse fixture: claude absent
        assert result.scope == "project"
        assert result.approved is True
        assert result.fallback_reason is not None
        assert "PATH" in result.fallback_reason
        assert (tmp_path / ".claude" / "settings.local.json").exists()

    def test_scope_local_does_not_silently_fall_back(self, tmp_path: Path):
        """An explicit --scope local must report, not quietly do something
        else."""
        result = install_mcp(tmp_path, scope="local")
        assert result.scope == "local"
        assert result.approved is False
        assert result.fallback_reason is not None

    def test_scope_project_never_shells_out(self, tmp_path: Path):
        with patch("brainpalace_cli.commands.install_mcp.subprocess.run") as run:
            result = install_mcp(tmp_path, scope="project")
        run.assert_not_called()
        assert result.scope == "project"
        assert result.approved is True

    def test_already_registered_skips_the_add(self, tmp_path: Path):
        """`claude mcp add` exits 1 with 'already exists', so re-running must
        detect first rather than treat that as a failure."""
        with (
            patch(
                "brainpalace_cli.commands.install_mcp.local_scope_has_server",
                return_value=True,
            ),
            patch("brainpalace_cli.commands.install_mcp.subprocess.run") as run,
        ):
            changed, err = register_local_scope(tmp_path)
        run.assert_not_called()
        assert changed is False
        assert err is None

    def test_add_failure_surfaces_reason(self, tmp_path: Path):
        with (
            patch(
                "brainpalace_cli.commands.install_mcp.which",
                return_value="/usr/bin/claude",
            ),
            patch("brainpalace_cli.commands.install_mcp.subprocess.run") as run,
        ):
            run.return_value.returncode = 1
            run.return_value.stderr = "boom"
            run.return_value.stdout = ""
            changed, err = register_local_scope(tmp_path)
        assert changed is False
        assert err is not None and "boom" in err

    def test_unknown_scope_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unknown scope"):
            install_mcp(tmp_path, scope="global")


class TestLocalScopeDetection:
    def test_reads_project_entry_from_home_config(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".claude.json").write_text(
            json.dumps(
                {"projects": {"/some/proj": {"mcpServers": {"brainpalace": {}}}}}
            )
        )
        with patch("brainpalace_cli.commands.install_mcp.Path.home", return_value=home):
            assert local_scope_has_server(Path("/some/proj")) is True
            assert local_scope_has_server(Path("/other/proj")) is False

    def test_missing_home_config_is_not_registered(self, tmp_path: Path):
        with patch(
            "brainpalace_cli.commands.install_mcp.Path.home", return_value=tmp_path
        ):
            assert local_scope_has_server(Path("/any")) is False


class TestRestartNotice:
    """D17 — the notice must never assert the tools are unavailable when the
    entry was already present (the dogfooded defect)."""

    def test_already_installed_notice_is_conditional(self):
        notice = restart_notice(changed=False, is_tty=False)
        # must NOT flatly assert unavailability, and must NOT tell the agent
        # to claim/deny availability of a session it cannot observe
        assert "are NOT available" not in notice
        assert "Do NOT claim" not in notice
        assert "if the" in notice.lower()  # conditional phrasing

    def test_already_installed_same_on_tty_and_not(self):
        # nothing changed -> nothing to ask; both channels say the same thing
        assert restart_notice(changed=False, is_tty=True) == restart_notice(
            changed=False, is_tty=False
        )

    def test_fresh_write_tty_is_plain_line(self):
        notice = restart_notice(changed=True, is_tty=True)
        assert "restart" in notice.lower()
        assert "AskUserQuestion" not in notice  # a human reads this directly

    def test_fresh_write_non_tty_is_askuserquestion_directive(self):
        notice = restart_notice(changed=True, is_tty=False)
        assert "AskUserQuestion" in notice  # agent path: directive, not prose

    def test_approved_notice_does_not_ask_user_to_approve(self):
        """We recorded approval, so telling them to approve is busywork
        pointing at a prompt that will not appear."""
        for is_tty in (True, False):
            notice = restart_notice(changed=True, is_tty=is_tty, approved=True)
            assert "approve the project" not in notice
            assert "restart" in notice.lower()

    def test_approved_notice_still_warns_about_folder_trust(self):
        """Folder trust outranks the allowlist and is not ours to grant: an
        untrusted folder holds the server at 'Pending approval' even with
        enabledMcpjsonServers set (verified empirically). Dropping this
        sentence would strand the user the approval was meant to unstrand."""
        for is_tty in (True, False):
            notice = restart_notice(changed=True, is_tty=is_tty, approved=True)
            assert "trust" in notice.lower()

    def test_unapproved_notice_still_says_to_approve(self):
        """--no-approve / explicit disable: the server WILL sit at 'Pending
        approval', so a restart alone strands the user."""
        for is_tty in (True, False):
            notice = restart_notice(changed=True, is_tty=is_tty, approved=False)
            assert "approv" in notice.lower()

    def test_unapproved_non_tty_still_uses_directive(self):
        notice = restart_notice(changed=True, is_tty=False, approved=False)
        assert "AskUserQuestion" in notice

    def test_local_scope_notice_does_not_mention_trust(self):
        """Local scope needs no folder trust — verified in an untrusted /tmp
        folder. Warning about a trust prompt that will not appear is the same
        overclaiming as promising approval was automatic."""
        for is_tty in (True, False):
            notice = restart_notice(
                changed=True, is_tty=is_tty, approved=True, scope="local"
            )
            assert "trust" not in notice.lower()
            assert "restart" in notice.lower()

    def test_local_scope_non_tty_still_uses_directive(self):
        notice = restart_notice(
            changed=True, is_tty=False, approved=True, scope="local"
        )
        assert "AskUserQuestion" in notice

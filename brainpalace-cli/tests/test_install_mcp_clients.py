"""Tests for `brainpalace install-mcp --client` (Phase B, tasks B1-B4).

Covers the non-Claude MCP clients added on top of the existing Claude-only
`install_mcp()` path: per-client path/top_key/entry shape (grounded in
docs/MCP_SETUP.md's table), idempotent JSON merge, never-clobber of foreign
servers/keys, the JSONC print-fallback (D4) that refuses to touch a file
with comments it cannot safely round-trip, Cline's globalStorage detection
(D5), and a regression pin that `--client claude` (the default) is
byte-for-byte unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from brainpalace_cli.commands.install_mcp import (
    _SERVER_CONFIG,
    _SERVER_KEY,
    MCP_CLIENTS,
    _jsonc_has_comments,
    install_mcp_command,
    merge_server,
    write_client_config,
)

_BASE_ENTRY = {"command": "brainpalace", "args": ["mcp", "--ensure-server"]}


def _cline_ext_dir(home: Path) -> Path:
    """The VS Code extension globalStorage dir Cline's config lives under."""
    code_user = home / ".config" / "Code" / "User"
    return code_user / "globalStorage" / "saoudrizwan.claude-dev"


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test runs with CWD = an isolated temp "project root"."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def home(tmp_path: Path):
    """Patch Path.home() to an isolated dir for the whole test.

    Critical for isolation: install_mcp.py's global-scope resolvers call
    ``Path.home()`` (not ``Path(...).expanduser()``, which does NOT go
    through ``Path.home()`` and would silently hit the real home directory
    on the machine running the suite).
    """
    fake_home = tmp_path / "_home"
    fake_home.mkdir()
    with patch(
        "brainpalace_cli.commands.install_mcp.Path.home", return_value=fake_home
    ):
        yield fake_home


class TestClientShapesGroundedInDocs:
    """Pins the exact path/top_key/entry per client from the Phase B spec's
    grounded table (docs/MCP_SETUP.md) — hardcoded expectations, not derived
    from the registry, so a regression in MCP_CLIENTS itself is caught."""

    @pytest.mark.parametrize(
        "client,scope,rooted_at_home,rel_path,top_key,expected_entry",
        [
            ("cursor", "project", False, ".cursor/mcp.json", "mcpServers", _BASE_ENTRY),
            ("cursor", "global", True, ".cursor/mcp.json", "mcpServers", _BASE_ENTRY),
            (
                "windsurf",
                "global",
                True,
                ".codeium/windsurf/mcp_config.json",
                "mcpServers",
                _BASE_ENTRY,
            ),
            (
                "vscode",
                "project",
                False,
                ".vscode/mcp.json",
                "servers",
                {"type": "stdio", **_BASE_ENTRY},
            ),
            (
                "kilo",
                "project",
                False,
                ".kilo/kilo.jsonc",
                "mcp",
                {
                    "type": "local",
                    "command": ["brainpalace", "mcp", "--ensure-server"],
                    "enabled": True,
                    "timeout": 30000,
                },
            ),
            (
                "kilo",
                "global",
                True,
                ".config/kilo/kilo.jsonc",
                "mcp",
                {
                    "type": "local",
                    "command": ["brainpalace", "mcp", "--ensure-server"],
                    "enabled": True,
                    "timeout": 30000,
                },
            ),
            (
                "qwen",
                "project",
                False,
                ".qwen/settings.json",
                "mcpServers",
                _BASE_ENTRY,
            ),
            ("qwen", "global", True, ".qwen/settings.json", "mcpServers", _BASE_ENTRY),
            ("kimi", "global", True, ".kimi/mcp.json", "mcpServers", _BASE_ENTRY),
        ],
    )
    def test_path_top_key_and_entry_shape(
        self,
        client: str,
        scope: str,
        rooted_at_home: bool,
        rel_path: str,
        top_key: str,
        expected_entry: dict,
        tmp_path: Path,
        home: Path,
    ):
        result = write_client_config(client, scope)
        expected_root = home if rooted_at_home else tmp_path
        assert result.path == expected_root / rel_path
        assert result.top_key == top_key
        assert result.wrote is True
        written = json.loads(result.path.read_text())
        assert written[top_key][_SERVER_KEY] == expected_entry

    @pytest.mark.parametrize(
        "client,rooted_at_home,rel_path",
        [
            ("cursor", True, ".cursor/mcp.json"),
            ("windsurf", True, ".codeium/windsurf/mcp_config.json"),
            ("vscode", False, ".vscode/mcp.json"),
            ("kilo", False, ".kilo/kilo.jsonc"),
            ("qwen", False, ".qwen/settings.json"),
            ("kimi", True, ".kimi/mcp.json"),
        ],
    )
    def test_default_scope_matches_grounded_table(
        self,
        client: str,
        rooted_at_home: bool,
        rel_path: str,
        tmp_path: Path,
        home: Path,
    ):
        """D6 — no --scope given falls back to each client's own default_scope."""
        result = write_client_config(client)  # scope=None
        expected_root = home if rooted_at_home else tmp_path
        assert result.path == expected_root / rel_path

    def test_every_registered_client_has_a_descriptor(self):
        assert set(MCP_CLIENTS) == {
            "cursor",
            "windsurf",
            "vscode",
            "kilo",
            "cline",
            "qwen",
            "kimi",
        }

    def test_unknown_client_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unknown client"):
            write_client_config("nonexistent")

    def test_unknown_scope_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="unknown scope"):
            write_client_config("cursor", "auto")  # claude-only scope


class TestIdempotentAndNoClobber:
    def test_idempotent_rerun_no_duplicate(self, tmp_path: Path):
        first = write_client_config("cursor", "project")
        assert first.wrote is True
        before = first.path.read_text()

        second = write_client_config("cursor", "project")
        assert second.wrote is False
        assert second.path.read_text() == before

    def test_never_clobbers_foreign_server_json_client(self, tmp_path: Path):
        path = tmp_path / ".qwen" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "mcpServers": {"other": {"command": "npx", "args": ["-y", "foo"]}},
                    "unrelatedTopLevelKey": True,
                }
            )
        )
        result = write_client_config("qwen", "project")
        assert result.wrote is True
        data = json.loads(path.read_text())
        assert data["mcpServers"]["other"] == {"command": "npx", "args": ["-y", "foo"]}
        assert data["unrelatedTopLevelKey"] is True
        assert data["mcpServers"][_SERVER_KEY] == _BASE_ENTRY

    def test_never_clobbers_foreign_server_jsonc_client_no_comments(
        self, tmp_path: Path
    ):
        """A comment-free JSONC file (kilo) merges exactly like plain JSON."""
        path = tmp_path / ".kilo" / "kilo.jsonc"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"mcp": {"other-server": {"type": "local"}}}))
        result = write_client_config("kilo", "project")
        assert result.wrote is True
        assert result.needs_manual is False
        data = json.loads(path.read_text())
        assert data["mcp"]["other-server"] == {"type": "local"}
        assert data["mcp"][_SERVER_KEY]["type"] == "local"  # our entry, not clobbered

    def test_malformed_existing_file_fails_loudly(self, tmp_path: Path):
        path = tmp_path / ".qwen" / "settings.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json")
        with pytest.raises(ValueError, match="Could not parse"):
            write_client_config("qwen", "project")
        assert path.read_text() == "{ not json"  # never overwritten


class TestJsoncPrintFallback:
    """D4 — a JSONC file with comments must never be rewritten."""

    @pytest.mark.parametrize(
        "client,rel_path",
        [("vscode", ".vscode/mcp.json"), ("kilo", ".kilo/kilo.jsonc")],
    )
    def test_comments_trigger_manual_fallback(
        self, client: str, rel_path: str, tmp_path: Path
    ):
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True)
        original = '{\n  // a user comment\n  "unrelated": true\n}\n'
        path.write_text(original)

        result = write_client_config(client, "project")

        assert result.wrote is False
        assert result.needs_manual is True
        assert result.snippet is not None
        assert _SERVER_KEY in result.snippet
        # the file must be byte-for-byte untouched — never corrupt the comment
        assert path.read_text() == original

    def test_block_comment_also_triggers_fallback(self, tmp_path: Path):
        path = tmp_path / ".vscode" / "mcp.json"
        path.parent.mkdir(parents=True)
        original = '{\n  /* block comment */\n  "servers": {}\n}\n'
        path.write_text(original)
        result = write_client_config("vscode", "project")
        assert result.wrote is False
        assert result.needs_manual is True
        assert path.read_text() == original

    def test_comment_free_jsonc_is_written_normally(self, tmp_path: Path):
        """No comments -> comment-free JSONC parses as plain JSON (D4)."""
        path = tmp_path / ".vscode" / "mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text('{\n  "servers": {}\n}\n')
        result = write_client_config("vscode", "project")
        assert result.wrote is True
        assert result.needs_manual is False

    def test_string_containing_slashes_is_not_a_false_positive(self, tmp_path: Path):
        """A URL-like string value must not be mistaken for a comment."""
        path = tmp_path / ".vscode" / "mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"servers": {"x": {"url": "https://example.com/a"}}})
        )
        result = write_client_config("vscode", "project")
        assert result.wrote is True
        assert result.needs_manual is False


class TestJsoncHasComments:
    """Direct unit coverage of the comment-detector D4 safety hinges on."""

    def test_no_comments(self):
        text = '{"a": 1, "b": "//not a comment inside code? no this is text"}'
        assert _jsonc_has_comments(text) is False

    def test_line_comment_detected(self):
        assert _jsonc_has_comments('{\n// hi\n"a": 1}') is True

    def test_block_comment_detected(self):
        assert _jsonc_has_comments('{/* hi */ "a": 1}') is True

    def test_slash_inside_string_is_not_a_comment(self):
        assert _jsonc_has_comments('{"url": "https://example.com"}') is False

    def test_escaped_quote_does_not_break_string_tracking(self):
        text = '{"a": "she said \\"//not a comment\\""}'
        assert _jsonc_has_comments(text) is False


class TestClineGlobalStorage:
    """D5 — locate, don't fabricate: the extension's dir must already exist."""

    def test_needs_manual_when_extension_absent(self, tmp_path: Path, home: Path):
        result = write_client_config("cline", "project")
        assert result.wrote is False
        assert result.needs_manual is True
        assert result.snippet is not None
        assert _SERVER_KEY in result.snippet
        # never fabricate the extension's storage dir
        assert not result.path.parent.parent.exists()

    def test_writes_when_extension_dir_present(self, tmp_path: Path, home: Path):
        ext_dir = _cline_ext_dir(home)
        ext_dir.mkdir(parents=True)
        result = write_client_config("cline", "project")
        assert result.wrote is True
        assert result.needs_manual is False
        assert result.path == ext_dir / "settings" / "cline_mcp_settings.json"
        data = json.loads(result.path.read_text())
        assert data["mcpServers"][_SERVER_KEY] == {**_BASE_ENTRY, "disabled": False}

    def test_never_clobbers_existing_cline_settings(self, tmp_path: Path, home: Path):
        ext_dir = _cline_ext_dir(home)
        settings_dir = ext_dir / "settings"
        settings_dir.mkdir(parents=True)
        settings_path = settings_dir / "cline_mcp_settings.json"
        settings_path.write_text(
            json.dumps({"mcpServers": {"other": {"command": "npx"}}, "extra": 1})
        )
        result = write_client_config("cline", "project")
        assert result.wrote is True
        data = json.loads(settings_path.read_text())
        assert data["mcpServers"]["other"] == {"command": "npx"}
        assert data["extra"] == 1
        assert data["mcpServers"][_SERVER_KEY]["disabled"] is False

    def test_idempotent_rerun(self, tmp_path: Path, home: Path):
        ext_dir = _cline_ext_dir(home)
        ext_dir.mkdir(parents=True)
        write_client_config("cline", "project")
        second = write_client_config("cline", "project")
        assert second.wrote is False


class TestMergeServerGeneralisation:
    """A2 — merge_server is the generalised primitive merge_mcp_config wraps."""

    def test_merge_server_arbitrary_top_key(self):
        merged, changed = merge_server({}, "servers", "brainpalace", {"a": 1})
        assert changed is True
        assert merged == {"servers": {"brainpalace": {"a": 1}}}

    def test_merge_server_idempotent(self):
        once, changed1 = merge_server({}, "mcp", "brainpalace", {"x": 1})
        assert changed1 is True
        twice, changed2 = merge_server(once, "mcp", "brainpalace", {"x": 1})
        assert changed2 is False
        assert twice == once

    def test_merge_server_does_not_mutate_input(self):
        existing = {"servers": {"foo": {"a": 1}}}
        merge_server(existing, "servers", "brainpalace", {"b": 2})
        assert _SERVER_KEY not in existing["servers"]


class TestClaudeClientRegressionUnchanged:
    """B3's dispatch must not perturb --client claude (the default) at all."""

    def test_default_client_writes_mcp_json_with_original_shape(self, tmp_path: Path):
        runner = CliRunner()
        with patch("brainpalace_cli.commands.install_mcp.which", return_value=None):
            result = runner.invoke(install_mcp_command, ["--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["status"] == "installed"
        assert payload["scope"] == "project"
        assert payload["approved"] is True
        assert payload["mcp_json"] == str(tmp_path / ".mcp.json")
        written = json.loads((tmp_path / ".mcp.json").read_text())
        # No --ensure-server for Claude (D2) — its config predates the flag
        # and must not change.
        assert written["mcpServers"][_SERVER_KEY] == {
            "command": "brainpalace",
            "args": ["mcp"],
        }
        assert written["mcpServers"][_SERVER_KEY] == _SERVER_CONFIG

    def test_explicit_client_claude_matches_default(self, tmp_path: Path):
        runner = CliRunner()
        with patch("brainpalace_cli.commands.install_mcp.which", return_value=None):
            default_result = runner.invoke(install_mcp_command, ["--json"])
        (tmp_path / ".mcp.json").unlink()
        (tmp_path / ".claude" / "settings.local.json").unlink()
        with patch("brainpalace_cli.commands.install_mcp.which", return_value=None):
            explicit_result = runner.invoke(
                install_mcp_command, ["--client", "claude", "--json"]
            )
        assert json.loads(default_result.output) == json.loads(explicit_result.output)

    def test_no_approve_still_works_under_client_dispatch(self, tmp_path: Path):
        runner = CliRunner()
        with patch("brainpalace_cli.commands.install_mcp.which", return_value=None):
            result = runner.invoke(install_mcp_command, ["--no-approve", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["approved"] is False
        assert not (tmp_path / ".claude" / "settings.local.json").exists()

    @pytest.mark.parametrize("scope", ["auto", "local", "project"])
    def test_claude_scope_choices_still_accepted(self, scope: str, tmp_path: Path):
        runner = CliRunner()
        with patch("brainpalace_cli.commands.install_mcp.which", return_value=None):
            result = runner.invoke(install_mcp_command, ["--scope", scope, "--json"])
        assert result.exit_code == 0

    def test_claude_rejects_non_claude_scope(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            install_mcp_command, ["--client", "claude", "--scope", "global", "--json"]
        )
        assert result.exit_code == 1
        assert "error" in json.loads(result.output)


class TestGenericClientCliDispatch:
    def test_cli_writes_cursor_config(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            install_mcp_command, ["--client", "cursor", "--scope", "project", "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload == {
            "client": "cursor",
            "path": str(tmp_path / ".cursor" / "mcp.json"),
            "wrote": True,
            "top_key": "mcpServers",
        }

    def test_cli_rejects_claude_only_scope_for_other_client(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            install_mcp_command, ["--client", "cursor", "--scope", "local", "--json"]
        )
        assert result.exit_code == 1
        assert "error" in json.loads(result.output)

    def test_cli_reports_needs_manual_for_cline_without_extension(
        self, tmp_path: Path, home: Path
    ):
        runner = CliRunner()
        result = runner.invoke(install_mcp_command, ["--client", "cline", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["wrote"] is False
        assert payload["needs_manual"] is True
        assert "snippet" in payload

    def test_cli_plain_output_prints_snippet_for_needs_manual(
        self, tmp_path: Path, home: Path
    ):
        runner = CliRunner()
        result = runner.invoke(install_mcp_command, ["--client", "cline"])
        assert result.exit_code == 0
        assert _SERVER_KEY in result.output
        assert "path:" in result.output

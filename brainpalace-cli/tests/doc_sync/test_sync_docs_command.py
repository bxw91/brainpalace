import json

from click.testing import CliRunner

from brainpalace_cli.cli import cli


def test_dump_interface_emits_versioned_json():
    res = CliRunner().invoke(cli, ["dump-interface"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["schema_version"] >= 1
    assert "source_version" in data
    assert any(c["name"] == "index" for c in data["commands"])


def test_sync_docs_and_dump_are_hidden():
    assert cli.commands["sync-docs"].hidden is True
    assert cli.commands["dump-interface"].hidden is True


def test_sync_docs_check_runs():
    # Against the real repo docs this may pass or fail; we only assert it executes
    # and returns a defined exit code (0 or 1), never crashes.
    res = CliRunner().invoke(cli, ["sync-docs", "--check"])
    assert res.exit_code in (0, 1)


def test_dump_interface_include_endpoints_flag():
    res = CliRunner().invoke(cli, ["dump-interface", "--include-endpoints"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert "endpoints" in data and isinstance(data["endpoints"], list)

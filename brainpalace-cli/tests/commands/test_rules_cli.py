from click.testing import CliRunner

from brainpalace_cli.commands.rules import rules_group


def test_rules_group_has_subcommands():
    assert set(rules_group.commands) >= {"list", "add", "retire", "show"}


def test_rules_list_invokes_endpoint(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, base_url):
            captured["url"] = base_url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def _request(self, method, path, **kw):
            captured["call"] = (method, path)
            return {"rules": []}

    monkeypatch.setattr("brainpalace_cli.commands.rules.DocServeClient", FakeClient)
    monkeypatch.setattr(
        "brainpalace_cli.commands.rules.get_server_url", lambda: "http://x"
    )
    result = CliRunner().invoke(rules_group, ["list"])
    assert result.exit_code == 0
    assert captured["call"] == ("GET", "/rules")

from brainpalace_cli.doc_sync.triggers import is_interface_source


def test_interface_paths_match():
    assert is_interface_source("brainpalace-cli/brainpalace_cli/cli.py")
    assert is_interface_source("brainpalace-cli/brainpalace_cli/commands/query.py")
    assert is_interface_source("brainpalace-cli/brainpalace_cli/config_schema.py")
    assert is_interface_source("brainpalace-cli/brainpalace_cli/mcp_server/server.py")
    assert is_interface_source(
        "brainpalace-server/brainpalace_server/api/routers/index.py"
    )
    assert is_interface_source("brainpalace-plugin/skills/using-brainpalace/SKILL.md")


def test_non_interface_paths_do_not_match():
    assert not is_interface_source("README.md")
    assert not is_interface_source("brainpalace-plugin/commands/brainpalace-query.md")
    assert not is_interface_source("brainpalace-cli/tests/doc_sync/test_facts.py")

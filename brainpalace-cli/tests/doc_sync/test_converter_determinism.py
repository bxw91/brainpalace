from brainpalace_cli.runtime.opencode_converter import OpenCodeConverter
from brainpalace_cli.runtime.types import PluginCommand


def _cmd():
    return PluginCommand(
        name="brainpalace-x", description="x", parameters=[], body="# X\n", skills=[]
    )


def test_convert_command_is_deterministic():
    c = OpenCodeConverter()
    assert c.convert_command(_cmd()) == c.convert_command(_cmd())

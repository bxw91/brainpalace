import inspect

from brainpalace_cli.commands import config as config_cmd


def test_wizard_template_uses_sqlite_store_type():
    # The wizard's graphrag templates must default to sqlite (persistent,
    # temporal), never the ephemeral in-memory 'simple'.
    src = inspect.getsource(config_cmd)
    assert '"store_type": "simple"' not in src
    assert src.count('"store_type": "sqlite"') >= 2

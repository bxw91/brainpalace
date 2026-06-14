# brainpalace-cli/tests/doc_sync/test_introspect.py
import click

from brainpalace_cli.doc_sync.facts import InterfaceSnapshot
from brainpalace_cli.doc_sync.introspect import snapshot_from_group


def _fake_group():
    @click.group()
    def g():  # noqa: D401
        pass

    @click.command()
    @click.option("--force", is_flag=True, default=False, help="Force it")
    @click.argument("path")
    def index(force, path):
        pass

    @click.command(hidden=True)
    def secret():
        pass

    g.add_command(index, name="index")
    g.add_command(secret, name="secret")
    return g


def test_snapshot_lists_commands_and_flags():
    snap = snapshot_from_group(_fake_group(), source_version="9.9.9")
    assert isinstance(snap, InterfaceSnapshot)
    assert snap.source_version == "9.9.9"
    idx = next(c for c in snap.commands if c.name == "index")
    assert any(f.name == "force" and f.type == "bool" for f in idx.flags)


def test_snapshot_records_hidden():
    snap = snapshot_from_group(_fake_group(), source_version="9.9.9")
    secret = next(c for c in snap.commands if c.name == "secret")
    assert secret.hidden is True

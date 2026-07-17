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


def _flag_value_pair_group():
    """A ``--project``/``--global`` pair writing ONE dest, as install-agent does."""

    @click.group()
    def g():  # noqa: D401
        pass

    @click.command()
    @click.option(
        "--project",
        "scope",
        flag_value="project",
        default=True,
        help="Project (default)",
    )
    @click.option("--global", "scope", flag_value="global", help="User-level")
    @click.option("--plain", is_flag=True, default=True, help="A real boolean flag")
    def install_agent(scope, plain):
        pass

    g.add_command(install_agent, name="install-agent")
    return g


def _flags_of(snap: InterfaceSnapshot, cmd: str) -> dict:
    return {f.name: f for f in {c.name: c for c in snap.commands}[cmd].flags}


def test_flag_value_default_is_the_resolved_value_not_literal_true():
    # Click resolves scope's default to the member's flag_value; publishing the
    # raw default=True stated a contract fact no invocation can produce, and
    # permanently failed doc-sync against a CORRECT doc.
    snap = snapshot_from_group(_flag_value_pair_group(), source_version="0")
    flags = _flags_of(snap, "install-agent")
    assert flags["project"].default == "project"


def test_flag_value_non_default_member_keeps_its_unset_default():
    snap = snapshot_from_group(_flag_value_pair_group(), source_version="0")
    flags = _flags_of(snap, "install-agent")
    assert flags["global"].default is None


def test_plain_boolean_flag_default_is_untouched():
    # The narrow rule must not rewrite an ordinary is_flag boolean to its
    # flag_value; True stays True.
    snap = snapshot_from_group(_flag_value_pair_group(), source_version="0")
    flags = _flags_of(snap, "install-agent")
    assert flags["plain"].default is True


def test_introspected_default_matches_click_own_resolution():
    # The contract must agree with what Click hands the callback at runtime.
    g = _flag_value_pair_group()
    cmd = g.commands["install-agent"]
    ctx = click.Context(cmd)
    resolved = next(
        p.get_default(ctx) for p in cmd.params if "--project" in getattr(p, "opts", [])
    )
    snap = snapshot_from_group(g, source_version="0")
    assert _flags_of(snap, "install-agent")["project"].default == resolved

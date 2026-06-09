"""Orphan BrainPalace server detection + reaping (pure, injectable core)."""

from brainpalace_cli.commands.reap import (
    find_orphan_pids,
    reap_orphans,
    referenced_pids,
)


def test_referenced_pids_only_alive_registry_entries():
    registry = {
        "/p/a": {"pid": 100, "base_url": "http://127.0.0.1:8000"},
        "/p/b": {"pid": 200, "base_url": "http://127.0.0.1:8001"},
    }
    alive = {100}.__contains__
    assert referenced_pids(registry, alive_fn=alive) == {100}


def test_find_orphan_pids_is_running_minus_referenced():
    assert sorted(find_orphan_pids([100, 200, 300], {100})) == [200, 300]


def test_reap_orphans_kills_only_unreferenced():
    killed = []
    registry = {"/p/a": {"pid": 100}}
    result = reap_orphans(
        kill_fn=killed.append,
        list_server_pids_fn=lambda: [100, 200, 300],
        registry_loader=lambda: registry,
        alive_fn=lambda _pid: True,
    )
    assert sorted(killed) == [200, 300]
    assert sorted(result) == [200, 300]


# --------------------------------------------------------------------------- #
# CLI surfaces: stop --all and doctor --reap
# --------------------------------------------------------------------------- #
from click.testing import CliRunner  # noqa: E402

from brainpalace_cli.commands.stop import stop_command  # noqa: E402


def test_stop_all_reaps_orphans(monkeypatch):
    reaped = {"called": False}

    def fake_reap(**_kw):
        reaped["called"] = True
        return [201, 202]

    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans", fake_reap, raising=False
    )
    result = CliRunner().invoke(stop_command, ["--all"])
    assert result.exit_code == 0, result.output
    assert reaped["called"]
    assert "2" in result.output  # reported count


def test_stop_all_json_lists_reaped_pids(monkeypatch):
    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans",
        lambda **_kw: [201, 202],
        raising=False,
    )
    result = CliRunner().invoke(stop_command, ["--all", "--json"])
    assert result.exit_code == 0, result.output
    assert '"reaped_pids"' in result.output
    assert "201" in result.output


def test_doctor_reap_flag_runs_reaper(monkeypatch):
    from brainpalace_cli.commands.doctor import doctor_command

    seen = {"called": False}

    def fake_reap(**_kw):
        seen["called"] = True
        return [303]

    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans", fake_reap, raising=False
    )
    result = CliRunner().invoke(doctor_command, ["--reap", "--json"])
    assert seen["called"]
    assert '"reaped_pids"' in result.output

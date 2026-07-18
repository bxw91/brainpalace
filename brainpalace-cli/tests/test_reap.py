"""Orphan BrainPalace server detection + reaping (pure, injectable core)."""

from brainpalace_cli.commands.reap import (
    ReapOutcome,
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


def test_find_orphan_pids_excludes_child_of_referenced_server():
    # D5: a PID whose parent is a live, registry-referenced server is not an
    # orphan — it's the millisecond-wide fork window of the parent's own
    # subprocess call, not a leaked instance.
    ppid = {200: 100, 300: 999}.get
    assert find_orphan_pids([100, 200, 300], {100}, ppid_fn=ppid) == [300]


def test_reap_orphans_kills_only_unreferenced():
    killed = []
    registry = {"/p/a": {"pid": 100}}
    result = reap_orphans(
        kill_fn=lambda pid, sig: killed.append((pid, sig)),
        list_server_pids_fn=lambda: [100, 200, 300],
        registry_loader=lambda: registry,
        alive_fn=lambda pid: pid == 100,  # registry pid alive; orphans die on SIGTERM
        sleep_fn=lambda _secs: None,
    )
    assert sorted(p for p, _sig in killed) == [200, 300]
    assert result == ReapOutcome(reaped=[200, 300], survived=[])


def test_reap_orphans_escalates_sigterm_survivor_to_sigkill():
    import signal

    killed = []
    registry: dict = {}
    # Alive until SIGKILL is sent to it, then confirmed dead.
    state = {"sigkilled": False}

    def kill_fn(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        if sig == signal.SIGKILL:
            state["sigkilled"] = True

    result = reap_orphans(
        grace=1.0,
        poll=0.01,
        kill_fn=kill_fn,
        list_server_pids_fn=lambda: [200],
        registry_loader=lambda: registry,
        alive_fn=lambda _pid: not state["sigkilled"],
        sleep_fn=lambda _secs: None,
    )
    assert (200, signal.SIGTERM) in killed
    assert (200, signal.SIGKILL) in killed
    assert result == ReapOutcome(reaped=[200], survived=[])


def test_reap_orphans_reports_sigkill_survivor_honestly():
    registry: dict = {}
    result = reap_orphans(
        grace=1.0,
        poll=0.01,
        kill_fn=lambda pid, sig: None,
        list_server_pids_fn=lambda: [87051],
        registry_loader=lambda: registry,
        alive_fn=lambda _pid: True,  # never dies — deadlocked fork clone
        sleep_fn=lambda _secs: None,
    )
    assert result == ReapOutcome(reaped=[], survived=[87051])


# --------------------------------------------------------------------------- #
# CLI surfaces: stop --all and doctor --reap
# --------------------------------------------------------------------------- #
from click.testing import CliRunner  # noqa: E402

from brainpalace_cli.commands.stop import stop_command  # noqa: E402


def test_stop_all_reaps_orphans(monkeypatch):
    reaped = {"called": False}

    def fake_reap(**_kw):
        reaped["called"] = True
        return ReapOutcome(reaped=[201, 202], survived=[87051])

    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans", fake_reap, raising=False
    )
    result = CliRunner().invoke(stop_command, ["--all"])
    assert result.exit_code == 0, result.output
    assert reaped["called"]
    assert "2" in result.output  # reported count
    assert "87051" in result.output  # survivor line printed, not swallowed


def test_stop_all_json_lists_reaped_and_surviving_pids(monkeypatch):
    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans",
        lambda **_kw: ReapOutcome(reaped=[201, 202], survived=[87051]),
        raising=False,
    )
    result = CliRunner().invoke(stop_command, ["--all", "--json"])
    assert result.exit_code == 0, result.output
    assert '"reaped_pids"' in result.output
    assert "201" in result.output
    assert '"surviving_pids"' in result.output
    assert "87051" in result.output


def test_stop_all_force_skips_the_reaper_grace_window(monkeypatch):
    seen: dict = {}

    def fake_reap(**kwargs):
        seen.update(kwargs)
        return ReapOutcome(reaped=[], survived=[])

    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans", fake_reap, raising=False
    )
    result = CliRunner().invoke(stop_command, ["--all", "--force"])
    assert result.exit_code == 0, result.output
    assert seen.get("grace") == 0.0  # D4: --force skips the grace window


def test_doctor_reap_flag_runs_reaper(monkeypatch):
    from brainpalace_cli.commands.doctor import doctor_command

    seen = {"called": False}

    def fake_reap(**_kw):
        seen["called"] = True
        return ReapOutcome(reaped=[303], survived=[87051])

    monkeypatch.setattr(
        "brainpalace_cli.commands.reap.reap_orphans", fake_reap, raising=False
    )
    result = CliRunner().invoke(doctor_command, ["--reap", "--json"])
    assert seen["called"]
    assert '"reaped_pids"' in result.output
    assert '"surviving_pids"' in result.output
    assert "87051" in result.output

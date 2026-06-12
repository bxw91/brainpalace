"""Unit tests for #1 — refuse a second live server on one project.

``_refuse_if_incumbent_alive`` is the server-side backstop to the flock: it
probes the project's recorded ``runtime.json`` server and aborts startup when a
*different*, healthy process is already serving THIS project, rather than
letting a stale-lock cleanup admit a duplicate (which corrupts embedded Chroma).
"""

import os

import pytest

import brainpalace_server.api.main as main
from brainpalace_server.runtime import RuntimeState, write_runtime


def _state_dir(tmp_path):
    project = tmp_path / "proj"
    sd = project / ".brainpalace"
    sd.mkdir(parents=True)
    return project, sd


def test_no_runtime_is_noop(tmp_path):
    """No runtime.json → nothing to refuse."""
    _project, sd = _state_dir(tmp_path)
    main._refuse_if_incumbent_alive(sd)  # must not raise


def test_own_pid_record_is_noop(tmp_path, monkeypatch):
    """The CLI writes our own pid into runtime.json — never treat it as an
    incumbent, even if /health happens to answer."""
    project, sd = _state_dir(tmp_path)
    write_runtime(
        sd,
        RuntimeState(
            base_url="http://127.0.0.1:8000",
            pid=os.getpid(),
            project_root=str(project),
        ),
    )
    monkeypatch.setattr(
        main, "_probe_health", lambda *_a, **_k: {"project_root": str(project)}
    )
    main._refuse_if_incumbent_alive(sd)  # must not raise


def test_unreachable_incumbent_is_noop(tmp_path, monkeypatch):
    """A recorded server that doesn't answer → safe to reclaim, no refusal."""
    project, sd = _state_dir(tmp_path)
    write_runtime(
        sd,
        RuntimeState(
            base_url="http://127.0.0.1:9999", pid=99999999, project_root=str(project)
        ),
    )
    monkeypatch.setattr(main, "_probe_health", lambda *_a, **_k: None)
    main._refuse_if_incumbent_alive(sd)  # must not raise


def test_refuses_when_live_server_serves_this_project(tmp_path, monkeypatch):
    """A healthy server serving THIS project → refuse to start a duplicate."""
    project, sd = _state_dir(tmp_path)
    write_runtime(
        sd,
        RuntimeState(
            base_url="http://127.0.0.1:8000", pid=99999999, project_root=str(project)
        ),
    )
    monkeypatch.setattr(
        main, "_probe_health", lambda *_a, **_k: {"project_root": str(project)}
    )
    with pytest.raises(RuntimeError, match="already live for this project"):
        main._refuse_if_incumbent_alive(sd)


def test_does_not_refuse_for_unrelated_project_on_recycled_port(tmp_path, monkeypatch):
    """A healthy server on the recorded port but serving a DIFFERENT project
    (port reuse) must not block this project's startup."""
    project, sd = _state_dir(tmp_path)
    write_runtime(
        sd,
        RuntimeState(
            base_url="http://127.0.0.1:8000", pid=99999999, project_root=str(project)
        ),
    )
    monkeypatch.setattr(
        main,
        "_probe_health",
        lambda *_a, **_k: {"project_root": "/some/other/project"},
    )
    main._refuse_if_incumbent_alive(sd)  # must not raise

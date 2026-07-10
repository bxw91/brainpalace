import pytest

from brainpalace_server.services import session_context_service as scs
from brainpalace_server.services.session_context_service import curate_due


@pytest.fixture
def _mode(monkeypatch):
    def _set(mode: str) -> None:
        monkeypatch.setattr(scs, "resolve_extraction_mode", lambda consumer: mode)

    return _set


def test_curate_gate_off_when_extraction_off(tmp_path, _mode):
    _mode("off")
    assert curate_due(state_dir=tmp_path, memory_count=5) is False


def test_curate_gate_off_when_provider_only(tmp_path, _mode):
    # provider mode is the SERVER executor's job, not the in-session nudge.
    _mode("provider")
    assert curate_due(state_dir=tmp_path, memory_count=5) is False


@pytest.mark.parametrize("mode", ["subagent", "auto"])
def test_curate_gate_fires_for_insession_modes(tmp_path, _mode, mode):
    _mode(mode)
    # Pure predicate: no stamp yet → due; called twice → STILL due (no side effect).
    assert curate_due(state_dir=tmp_path, memory_count=5) is True
    assert curate_due(state_dir=tmp_path, memory_count=5) is True


def test_curate_gate_false_when_stamp_fresh(tmp_path, _mode):
    _mode("subagent")
    stamp = tmp_path / "state" / "last-curate"
    stamp.parent.mkdir()
    stamp.touch()
    assert curate_due(state_dir=tmp_path, memory_count=5) is False


def test_curate_gate_no_op_when_memory_empty(tmp_path, _mode):
    _mode("subagent")
    assert curate_due(state_dir=tmp_path, memory_count=0) is False


def test_curate_gate_true_when_stamp_stale(tmp_path, _mode, monkeypatch):
    _mode("subagent")
    stamp = tmp_path / "state" / "last-curate"
    stamp.parent.mkdir()
    stamp.touch()
    # Force the interval to 0 days so any stamp counts as stale.
    monkeypatch.setattr(scs.settings, "MEMORY_CURATE_INTERVAL_DAYS", 0)
    assert curate_due(state_dir=tmp_path, memory_count=5) is True

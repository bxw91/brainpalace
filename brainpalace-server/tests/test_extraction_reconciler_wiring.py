import time

from brainpalace_server.services.session_reconciler import (
    ExtractionDrainState,
    should_drain,
)


def test_cooldown_gates_drain():
    state = ExtractionDrainState()
    now = time.time()
    assert should_drain(state, cooldown=300, now=now) is True
    state.last_drain = now
    assert should_drain(state, cooldown=300, now=now + 10) is False
    assert should_drain(state, cooldown=300, now=now + 301) is True

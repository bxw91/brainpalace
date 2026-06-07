"""ConfigService.write blocks only on validation errors in CHANGED fields.

A config editor must not refuse to save because of a pre-existing value the
user never touched (a newly-valid enum the validator hasn't caught up to, a
legacy field, an other-tool section). It must still catch genuine mistakes in
fields the current save is editing.
"""

from __future__ import annotations

import pytest
import yaml

from brainpalace_dashboard.services.config_svc import ConfigService, ConfigWriteError


def _state(tmp_path, body: str):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(body)
    return state


def test_preexisting_invalid_untouched_field_does_not_block(tmp_path):
    """A bad enum value already on disk, in a field the user does NOT edit,
    must not block a save of a different field — and must be preserved."""
    state = _state(
        tmp_path,
        "embedding:\n  provider: some-future-provider\n"  # invalid per schema
        "summarization:\n  provider: anthropic\n",
    )
    svc = ConfigService()
    values = svc.read(state)
    values["summarization"]["provider"] = "openai"  # edit a DIFFERENT field
    svc.write(state, values)  # must NOT raise
    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["summarization"]["provider"] == "openai"
    assert saved["embedding"]["provider"] == "some-future-provider"  # preserved


def test_invalid_value_in_a_changed_field_is_blocked(tmp_path):
    """Editing a field TO an invalid value is still rejected."""
    state = _state(tmp_path, "embedding:\n  provider: openai\n")
    svc = ConfigService()
    values = svc.read(state)
    values["embedding"]["provider"] = "not-a-real-provider"
    with pytest.raises(ConfigWriteError) as ei:
        svc.write(state, values)
    assert any(e["field"] == "embedding.provider" for e in ei.value.errors)


def test_sqlite_graph_store_type_is_valid(tmp_path):
    """graphrag.store_type=sqlite (the current default) is accepted when set."""
    state = _state(tmp_path, "graphrag:\n  store_type: simple\n")
    svc = ConfigService()
    values = svc.read(state)
    values["graphrag"]["store_type"] = "sqlite"
    svc.write(state, values)  # must NOT raise
    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["graphrag"]["store_type"] == "sqlite"

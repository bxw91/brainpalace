"""The dashboard editor must tolerate unknown config sections/subfields.

Real config.yaml files carry legacy fields and other-tool sections the schema
does not model. The editor (unlike a strict linter) must never block a save on
"unknown top-level key" / "unknown key in section" — it must preserve them.
"""

import yaml

from brainpalace_dashboard.services.config_svc import ConfigService


def _state(tmp_path, body):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(body)
    return state


def test_write_tolerates_unknown_sections_and_subfields(tmp_path):
    body = (
        "embedding:\n"
        "  provider: openai\n"
        "some_future_section:\n"
        "  x: 1\n"
        "git_indexing:\n"
        "  enabled: false\n"
        "  default: legacy-value\n"
    )
    state = _state(tmp_path, body)
    svc = ConfigService()

    # Read full config, edit a known field, write the merged whole.
    values = svc.read(state)
    values["embedding"]["provider"] = "ollama"

    # Must NOT raise on the unknown section / unknown subfield.
    svc.write(state, values)

    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["embedding"]["provider"] == "ollama"
    # Unknown bits preserved verbatim.
    assert saved["some_future_section"] == {"x": 1}
    assert saved["git_indexing"]["default"] == "legacy-value"

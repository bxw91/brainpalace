"""Round-trip regression: a realistic config saves cleanly via the dashboard.

Before config_schema modeled bm25/git_indexing/session_indexing/
session_extraction, editing any field and saving the merged whole config blew
up with "unknown top-level key" errors — breaking the Config tab on every real
project. This proves a realistic config round-trips: read -> edit -> write
succeeds, the edit persists, and the previously-unmodeled sections survive.
"""

import yaml

from brainpalace_dashboard.services.config_svc import ConfigService

_REALISTIC = """\
api:
  host: 127.0.0.1
  port: 8765
embedding:
  provider: openai
  model: text-embedding-3-small
summarization:
  provider: anthropic
  model: claude-3-5-haiku-latest
graphrag:
  enabled: true
  store_type: simple
bm25:
  language: en
  engine: stem
  detect: false
  detect_min_confidence: 0.6
git_indexing:
  enabled: false
  depth: 1000
  max_files: 50
  path_filter: []
session_indexing:
  enabled: true
  retain_days: 0
  window: 4
  stride: 2
  watch_debounce_ms: 30000
  archive:
    enabled: true
session_extraction:
  mode: subagent
  quiescence_seconds: 1800
"""


def _state(tmp_path):
    state = tmp_path / ".brainpalace"
    state.mkdir()
    (state / "config.yaml").write_text(_REALISTIC)
    return state


def test_realistic_config_roundtrips(tmp_path):
    state = _state(tmp_path)
    svc = ConfigService()

    values = svc.read(state)
    values["embedding"]["provider"] = "ollama"

    # Must succeed (no ConfigWriteError) on a realistic full config.
    svc.write(state, values)

    saved = yaml.safe_load((state / "config.yaml").read_text())
    assert saved["embedding"]["provider"] == "ollama"
    # Previously-unmodeled sections survive untouched.
    assert saved["bm25"]["engine"] == "stem"
    assert saved["git_indexing"]["depth"] == 1000
    assert saved["session_indexing"]["window"] == 4
    assert saved["session_indexing"]["archive"] == {"enabled": True}
    assert saved["session_extraction"]["mode"] == "subagent"

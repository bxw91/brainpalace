"""Phase 060 — strict extraction model validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from brainpalace_server.models.session_extract import SessionExtraction


def _valid_payload() -> dict:
    return {
        "session_id": "s1",
        "project_path": "/work/proj",
        "branch": "main",
        "started_at": "2026-05-20T10:00:00Z",
        "ended_at": "2026-05-20T10:30:00Z",
        "summary": "Migrated config persistence to a hosted store.",
        "open_threads": ["wire up CI secret"],
        "decisions": [
            {
                "text": "Persist config in the hosted DB, not the filesystem",
                "rationale": "serverless runtime has no persistent fs",
                "files": ["api/config.js"],
                "supersedes": "filesystem persistence via data/config.json",
            }
        ],
        "files_touched": [{"path": "api/config.js", "action": "create"}],
        "tools_used": ["Write", "Bash"],
        "triplets": [
            {
                "subject": "api/config.js",
                "relation": "touches",
                "object": "config persistence",
                "evidence_turn": 4,
            }
        ],
    }


def test_full_payload_parses() -> None:
    m = SessionExtraction(**_valid_payload())
    assert m.session_id == "s1"
    assert m.decisions[0].files == ["api/config.js"]
    assert m.triplets[0].relation == "touches"


def test_minimal_payload_parses() -> None:
    m = SessionExtraction(session_id="s2", summary="did a thing")
    assert m.open_threads == [] and m.decisions == [] and m.triplets == []


def test_extra_top_level_key_rejected() -> None:
    payload = _valid_payload()
    payload["bogus"] = 1
    with pytest.raises(ValidationError):
        SessionExtraction(**payload)


def test_relation_outside_vocab_rejected() -> None:
    payload = _valid_payload()
    payload["triplets"][0]["relation"] = "free-text-relation"
    with pytest.raises(ValidationError):
        SessionExtraction(**payload)


def test_file_action_outside_vocab_rejected() -> None:
    payload = _valid_payload()
    payload["files_touched"][0]["action"] = "delete"
    with pytest.raises(ValidationError):
        SessionExtraction(**payload)


def test_missing_required_summary_rejected() -> None:
    with pytest.raises(ValidationError):
        SessionExtraction(session_id="s3")

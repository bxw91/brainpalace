"""Session filter contract (Task 7) — the documented kept/dropped block set.

This pins the single shared moderate-filter contract that both engines rely on
(`filter_transcript` for the provider engine; the `chat-session-extractor` agent
prompt for the subagent engine). If this changes, update the "Session filter
contract" section in docs/SESSION_INDEXING.md too.
"""

from __future__ import annotations

import json

from brainpalace_server.services.session_distill_service import filter_transcript

KEPT = ("text", "thinking", "tool_use", "tool_result")
DROPPED = ("attachment", "file-history-snapshot", "queue-operation")


def _line(obj: dict) -> str:
    return json.dumps(obj)


def test_filter_keeps_and_drops_contract(tmp_path):
    path = tmp_path / "s.jsonl"
    lines = [
        # KEPT: assistant text
        _line(
            {
                "type": "assistant",
                "sessionId": "s",
                "timestamp": "t",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "KEEP_TEXT"}],
                },
            }
        ),
        # KEPT: thinking
        _line(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "KEEP_THINK"}],
                },
            }
        ),
        # KEPT: tool_use (name + key inputs)
        _line(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "KEEP_FILE.py", "secret": "noise"},
                        }
                    ],
                },
            }
        ),
        # KEPT: tool_result (truncated)
        _line(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "KEEP_RESULT"}],
                },
            }
        ),
        # DROPPED: non-conversational record types
        _line({"type": "attachment", "data": "DROP_ATTACH"}),
        _line({"type": "file-history-snapshot", "data": "DROP_HISTORY"}),
        _line({"type": "queue-operation", "operation": "DROP_QUEUE"}),
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    out = filter_transcript(path)

    # Kept content is present.
    assert "KEEP_TEXT" in out
    assert "KEEP_THINK" in out
    assert "Edit" in out and "KEEP_FILE.py" in out
    assert "KEEP_RESULT" in out
    # tool_use keeps only key inputs, not arbitrary noise.
    assert "noise" not in out
    # Dropped record types never appear.
    assert "DROP_ATTACH" not in out
    assert "DROP_HISTORY" not in out
    assert "DROP_QUEUE" not in out

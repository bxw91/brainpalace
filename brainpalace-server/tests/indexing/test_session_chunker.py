"""Phase 050 — tests for the sliding-window session chunker."""

from __future__ import annotations

from pathlib import Path

from brainpalace_server.indexing.session_chunker import SessionChunker
from brainpalace_server.indexing.session_loader import SessionMeta, Turn, load_session

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sessions"
PARENT = FIXTURES / "sess-parent-1.jsonl"


def _meta(session_id: str = "s1", **kw: object) -> SessionMeta:
    base: dict[str, object] = {
        "session_id": session_id,
        "project_path": "/proj",
        "branch": "main",
        "started_at": "2026-05-20T10:00:00.000Z",
        "ended_at": "2026-05-20T10:10:00.000Z",
        "source_path": "/tmp/s1.jsonl",
        "is_subagent": False,
        "parent_session_id": None,
    }
    base.update(kw)
    return SessionMeta(**base)  # type: ignore[arg-type]


def _turns(n: int) -> list[Turn]:
    out = []
    for i in range(n):
        role = "assistant" if i % 2 else "user"
        out.append(Turn(i, role, "text", f"turn number {i} content"))
    return out


def test_sliding_window_respects_window_and_stride() -> None:
    chunker = SessionChunker(window=4, stride=2, include_user_turns=True)
    chunks = chunker.chunk(_meta(), _turns(8))
    # 8 turns, window 4, stride 2 → windows at 0,2,4 (last full window) = 3.
    assert len(chunks) == 3
    assert all(c.metadata.source_type == "session_turn" for c in chunks)
    assert chunks[0].metadata.extra["turn_index"] == 0
    assert chunks[1].metadata.extra["turn_index"] == 2


def test_user_turns_excluded_by_default() -> None:
    turns = [
        Turn(0, "user", "text", "SECRET user prompt do not index"),
        Turn(1, "assistant", "text", "assistant reply alpha"),
        Turn(2, "assistant", "tool_use", "", tool_name="Read",
             tool_inputs={"file_path": "a.py"}),
        Turn(3, "user", "tool_result", "result body"),
    ]
    chunks = SessionChunker(window=4, stride=4).chunk(_meta(), turns)
    blob = " ".join(c.text for c in chunks)
    assert "SECRET user prompt" not in blob  # user dialogue dropped
    assert "assistant reply alpha" in blob  # assistant kept
    assert "result body" in blob  # tool_result kept (not human dialogue)


def test_user_turns_included_when_opted_in() -> None:
    turns = [
        Turn(0, "user", "text", "include this user prompt"),
        Turn(1, "assistant", "text", "reply"),
    ]
    chunks = SessionChunker(window=4, stride=4, include_user_turns=True).chunk(
        _meta(), turns
    )
    assert "include this user prompt" in " ".join(c.text for c in chunks)


def test_metadata_captures_tools_and_files() -> None:
    turns = [
        Turn(0, "assistant", "tool_use", "", tool_name="Write",
             tool_inputs={"file_path": "src/app.py", "content": "x=1"}),
        Turn(1, "assistant", "tool_use", "", tool_name="Bash",
             tool_inputs={"command": "pytest"}),
    ]
    chunk = SessionChunker(window=4, stride=4).chunk(_meta(), turns)[0]
    extra = chunk.metadata.extra
    # List fields are stored as comma-joined strings (Chroma scalar metadata).
    assert extra["tools_used"].split(",") == ["Write", "Bash"]
    assert extra["files_touched"] == "src/app.py"  # DIRECT file inputs only
    assert extra["role_mix"] == "assistant"
    assert extra["session_id"] == "s1"
    assert extra["branch"] == "main"


def test_code_block_flag_and_language() -> None:
    turns = [
        Turn(0, "assistant", "text",
             "Here:\n```python\ndef f():\n    return 1\n```\ndone"),
    ]
    chunk = SessionChunker(window=4, stride=4).chunk(_meta(), turns)[0]
    assert chunk.metadata.extra["has_code_block"] is True
    assert chunk.metadata.extra["language"] == "python"


def test_chunk_id_is_deterministic_for_dedup() -> None:
    turns = _turns(4)
    a = SessionChunker(window=4, stride=2).chunk(_meta(), turns)
    b = SessionChunker(window=4, stride=2).chunk(_meta(), turns)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    # Different session id → different ids (no cross-session collision).
    c = SessionChunker(window=4, stride=2).chunk(_meta(session_id="other"), turns)
    assert a[0].chunk_id != c[0].chunk_id


def test_subagent_metadata_propagates() -> None:
    meta = _meta(session_id="sub", is_subagent=True, parent_session_id="parent")
    chunk = SessionChunker(window=4, stride=4).chunk(meta, _turns(2))[0]
    assert chunk.metadata.extra["is_subagent"] is True
    assert chunk.metadata.extra["parent_session_id"] == "parent"


def test_chunks_real_fixture_session() -> None:
    meta, turns = load_session(PARENT)
    chunks = SessionChunker(window=4, stride=2).chunk(meta, turns)
    assert chunks
    assert all(c.token_count > 0 for c in chunks)
    assert all(c.metadata.extra["session_id"] == "sess-parent-1" for c in chunks)

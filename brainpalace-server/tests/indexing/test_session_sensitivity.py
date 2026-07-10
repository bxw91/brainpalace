from __future__ import annotations

import json
from pathlib import Path

from brainpalace_server.indexing.chunking import ChunkMetadata
from brainpalace_server.indexing.session_chunker import SessionChunker
from brainpalace_server.indexing.session_loader import SessionMeta, Turn
from brainpalace_server.services.scan_compiler import ScanPlan
from brainpalace_server.services.scan_executor import scan_archive


def _meta(**kw):
    base = {
        "chunk_id": "c1",
        "source": "s",
        "file_name": "f",
        "chunk_index": 0,
        "total_chunks": 1,
        "source_type": "session_turn",
    }
    base.update(kw)
    return ChunkMetadata(**base)


def test_chunk_sensitivity_defaults_normal_and_always_emitted():
    d = _meta().to_dict()
    assert d["sensitivity"] == "normal"  # present on every chunk


def test_chunk_sensitivity_roundtrips():
    d = _meta(sensitivity="private").to_dict()
    assert d["sensitivity"] == "private"


def _session_meta(session_id="s1", sensitivity="normal"):
    return SessionMeta(
        session_id=session_id,
        project_path="/proj",
        branch="main",
        started_at="2026-05-20T10:00:00.000Z",
        ended_at="2026-05-20T10:10:00.000Z",
        source_path="/tmp/s1.jsonl",
        sensitivity=sensitivity,
    )


def _turns(n):
    out = []
    for i in range(n):
        role = "assistant" if i % 2 else "user"
        out.append(Turn(i, role, "text", f"turn number {i} content"))
    return out


def test_session_chunker_propagates_sensitivity():
    meta = _session_meta(sensitivity="private")
    chunks = SessionChunker(window=4, stride=2, include_user_turns=True).chunk(
        meta, _turns(8)
    )
    assert chunks  # sanity: chunker produced something
    assert all(c.metadata.sensitivity == "private" for c in chunks)


def _write_session(day_folder: Path, session_id: str, term: str):
    day_folder.mkdir(parents=True, exist_ok=True)
    f = day_folder / f"{session_id}.jsonl"
    lines = [
        {
            "type": "user",
            "sessionId": session_id,
            "message": {"role": "user", "content": f"{term} {term}"},
        },
    ]
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def test_scan_archive_skips_private_session(tmp_path):
    archive = tmp_path / "archive"
    day = archive / "2026-05-20-claude-code"
    _write_session(day, "pub-session", "widget")
    _write_session(day, "sec-session", "widget")
    plan = ScanPlan(term="widget")

    # default-deny: the private session's file is skipped
    hidden = scan_archive(
        archive,
        plan,
        private_session_ids={"sec-session"},
        include_sensitive=False,
    )
    assert dict(hidden).get(None) == 2  # only pub-session's two occurrences

    # revealed: both sessions counted
    revealed = scan_archive(
        archive,
        plan,
        private_session_ids={"sec-session"},
        include_sensitive=True,
    )
    assert dict(revealed).get(None) == 4

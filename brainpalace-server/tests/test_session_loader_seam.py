"""Task 13 — assert the single tool-format parser seam.

``load_session`` is the only Claude-Code-transcript record-format parser in the
extraction path. This test pins that contract via the documented ``# seam:``
marker so a second transcript parser can't be added silently without owning the
seam note (and the conversion to ``(SessionMeta, list[Turn])``).
"""

from __future__ import annotations

import inspect

from brainpalace_server.indexing import session_loader


def test_seam_marker_present_in_loader():
    src = inspect.getsource(session_loader)
    assert "# seam: single tool-format parser" in src
    # The seam note names the format-agnostic contract downstream consumes.
    assert "(SessionMeta, list[Turn])" in src or "(SessionMeta`` + ``list[Turn]" in src


def test_load_session_returns_meta_and_turns(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        '{"type": "user", "sessionId": "abc", '
        '"message": {"role": "user", "content": "hello"}}\n',
        encoding="utf-8",
    )
    meta, turns = session_loader.load_session(p)
    assert isinstance(meta, session_loader.SessionMeta)
    assert isinstance(turns, list)
    assert meta.session_id == "abc"

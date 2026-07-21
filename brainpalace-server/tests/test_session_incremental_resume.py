# tests/test_session_incremental_resume.py
import pytest

from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services import session_distill_service as sds
from brainpalace_server.services.session_distill_service import (
    read_progress,
    write_progress,
)


def _extraction(summary: str) -> SessionExtraction:
    return SessionExtraction(session_id="s1", summary=summary)


def test_progress_roundtrip(tmp_path):
    assert read_progress(str(tmp_path), "s1") is None  # absent
    write_progress(str(tmp_path), "s1", 12, _extraction("did X"))
    got = read_progress(str(tmp_path), "s1")
    assert got is not None
    offset, extraction = got
    assert offset == 12
    assert extraction.summary == "did X"


def test_progress_corrupt_returns_none(tmp_path):
    from brainpalace_server.services.session_distill_service import progress_path

    p = progress_path(str(tmp_path), "s1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert read_progress(str(tmp_path), "s1") is None  # tolerant


# ---------------------------------------------------------------------------
# 2b-6: prune orphaned resume sidecars (keep .done markers)
# ---------------------------------------------------------------------------
def test_prune_orphan_sidecars_removes_only_gone_keeps_marker(tmp_path):
    from brainpalace_server.services.session_distill_service import (
        marker_path,
        progress_path,
        prune_orphan_sidecars,
        write_marker,
    )

    write_progress(str(tmp_path), "live", 1, _extraction("a"))
    write_progress(str(tmp_path), "gone", 1, _extraction("b"))
    write_marker(tmp_path, "gone")  # marker must survive the prune

    removed = prune_orphan_sidecars(str(tmp_path), {"live"})

    assert removed == 1
    assert progress_path(str(tmp_path), "live").is_file()  # known → kept
    assert not progress_path(str(tmp_path), "gone").is_file()  # orphan → removed
    assert marker_path(tmp_path, "gone").is_file()  # .done untouched (re-distill safe)


def test_prune_orphan_sidecars_noop_without_dir(tmp_path):
    from brainpalace_server.services.session_distill_service import (
        prune_orphan_sidecars,
    )

    assert prune_orphan_sidecars(str(tmp_path), set()) == 0


# ---------------------------------------------------------------------------
# 2b-4: versioned sidecar (migration seam — no fleet re-distill on a model bump)
# ---------------------------------------------------------------------------
def test_progress_writes_version(tmp_path):
    import json

    from brainpalace_server.services.session_distill_service import (
        _SIDECAR_VERSION,
        progress_path,
    )

    write_progress(str(tmp_path), "s1", 3, _extraction("x"))
    obj = json.loads(progress_path(str(tmp_path), "s1").read_text(encoding="utf-8"))
    assert obj["v"] == _SIDECAR_VERSION


def test_progress_reads_legacy_without_version(tmp_path):
    import json

    from brainpalace_server.services.session_distill_service import progress_path

    p = progress_path(str(tmp_path), "s1")
    p.parent.mkdir(parents=True, exist_ok=True)
    # Pre-2b-4 sidecar: no "v" key.
    p.write_text(
        json.dumps({"offset": 7, "extraction": {"session_id": "s1", "summary": "old"}}),
        encoding="utf-8",
    )
    got = read_progress(str(tmp_path), "s1")
    assert got is not None and got[0] == 7  # legacy still resumes


def test_progress_future_version_returns_none(tmp_path):
    import json

    from brainpalace_server.services.session_distill_service import progress_path

    p = progress_path(str(tmp_path), "s1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"v": 999, "offset": 1, "extraction": {"session_id": "s1", "summary": "x"}}
        ),
        encoding="utf-8",
    )
    # Unknown future shape → resume safely declines (re-distill) instead of
    # misreading a format it doesn't understand.
    assert read_progress(str(tmp_path), "s1") is None


# ---------------------------------------------------------------------------
# Task 2 helpers
# ---------------------------------------------------------------------------


def _meta(session_id: str = "s1") -> "sds.SessionMeta":
    from brainpalace_server.indexing.session_loader import SessionMeta

    return SessionMeta(
        session_id=session_id,
        project_path=None,
        branch=None,
        started_at=None,
        ended_at=None,
        source_path="/tmp/fake.jsonl",
    )


class _Summarizer:
    """Returns a fixed valid extraction JSON regardless of prompt."""

    def __init__(self):
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return '{"summary": "did things", "decisions": [], "triplets": []}'


class _NoopStore:
    async def store(self, payload, **kw):
        return None


@pytest.mark.asyncio
async def test_fresh_distil_writes_progress_and_calls_store_once(tmp_path, monkeypatch):
    # A tiny fake transcript file the loader can read is heavy to construct;
    # instead patch load_session to return controlled turns.
    from brainpalace_server.indexing.session_loader import Turn

    meta = _meta("s1")
    turns = [Turn(0, "user", "text", "hello"), Turn(1, "assistant", "text", "hi")]
    monkeypatch.setattr(sds, "parse_transcript", lambda p: (meta, turns))
    summ = _Summarizer()
    monkeypatch.setattr(sds, "SessionExtractService", lambda: _NoopStore())

    await sds.distill_transcript(
        tmp_path / "s1.jsonl",
        summarizer=summ,
        embedder=None,
        storage_backend=None,
        project_root=str(tmp_path),
    )

    # exactly one generate() call (fresh single-pass — no merge), progress written
    assert len(summ.calls) == 1
    prog = sds.read_progress(str(tmp_path), "s1")
    assert prog is not None
    offset, extraction = prog
    assert offset == 1  # last turn index
    assert extraction.summary == "did things"


# ---------------------------------------------------------------------------
# 2b-3: per-session distill lock (no double-extract / lost-advance under races)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_distill_same_session_extracts_once(tmp_path, monkeypatch):
    import asyncio

    from brainpalace_server.indexing.session_loader import Turn

    meta = _meta("s1")
    turns = [Turn(0, "user", "text", "hello"), Turn(1, "assistant", "text", "hi")]
    monkeypatch.setattr(sds, "parse_transcript", lambda p: (meta, turns))
    monkeypatch.setattr(sds, "SessionExtractService", lambda: _NoopStore())

    class _SlowSummarizer:
        def __init__(self):
            self.calls = 0

        async def generate(self, prompt):
            self.calls += 1
            await asyncio.sleep(0.05)  # widen the race window
            return '{"summary": "did", "decisions": [], "triplets": []}'

    summ = _SlowSummarizer()
    await asyncio.gather(
        *[
            sds.distill_transcript(
                tmp_path / "s1.jsonl",
                summarizer=summ,
                embedder=None,
                storage_backend=None,
                project_root=str(tmp_path),
            )
            for _ in range(2)
        ]
    )

    # Lock serialized the RMW: the 2nd caller re-read the advanced offset, saw no
    # new turns, so extraction ran exactly once and the offset advanced once.
    assert summ.calls == 1
    prog = sds.read_progress(str(tmp_path), "s1")
    assert prog is not None and prog[0] == 1


# ---------------------------------------------------------------------------
# 2b-2: merge_extractions is structural (set-union + dedup), NO LLM
# ---------------------------------------------------------------------------
def test_merge_extractions_structural_union_no_llm():
    from brainpalace_server.models.session_extract import Decision, Triplet

    prior = SessionExtraction(
        session_id="s1",
        summary="old",
        decisions=[Decision(text="D1", rationale="because")],
        triplets=[Triplet(subject="a", relation="touches", object="f.py")],
        tools_used=["Edit"],
        open_threads=["t1"],
    )
    new = SessionExtraction(
        session_id="s1",
        summary="new part",
        decisions=[
            Decision(text="D1"),  # duplicate text → deduped
            Decision(text="D2"),  # new
        ],
        triplets=[
            Triplet(subject="a", relation="touches", object="f.py"),  # dup
            Triplet(subject="b", relation="decided", object="D2"),  # new
        ],
        tools_used=["Edit", "Bash"],
        open_threads=["t1", "t2"],
    )

    merged = sds.merge_extractions(prior, new, "s1")  # synchronous, no summarizer

    # Decisions deduped by text, prior wins (keeps its richer rationale).
    assert [d.text for d in merged.decisions] == ["D1", "D2"]
    assert merged.decisions[0].rationale == "because"
    # Triplets unioned + deduped by (subject, relation, object).
    assert len(merged.triplets) == 2
    assert merged.tools_used == ["Edit", "Bash"]
    assert merged.open_threads == ["t1", "t2"]
    # Both summary parts preserved (no LLM re-summarization → no loss).
    assert "old" in merged.summary and "new part" in merged.summary


# ---------------------------------------------------------------------------
# Task 4: resume branch in distill_transcript
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resume_distils_only_new_turns_and_merges(tmp_path, monkeypatch):
    from brainpalace_server.indexing.session_loader import Turn

    meta = _meta("s1")
    # Seed a prior progress sidecar at offset 1 (turns 0,1 already done).
    sds.write_progress(
        str(tmp_path), "s1", 1, SessionExtraction(session_id="s1", summary="old")
    )

    # Transcript now has turns 0..3 (2 new: indices 2,3).
    turns = [
        Turn(0, "user", "text", "OLD-A"),
        Turn(1, "assistant", "text", "OLD-B"),
        Turn(2, "user", "text", "NEW-C"),
        Turn(3, "assistant", "text", "NEW-D"),
    ]
    monkeypatch.setattr(sds, "parse_transcript", lambda p: (meta, turns))

    captured = {}

    class _ResumeSummarizer:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt):
            self.calls.append(prompt)
            # Only the new slice is distilled now; the merge is structural (no LLM).
            return '{"summary": "new only", "decisions": [], "triplets": []}'

    class _Store:
        async def store(self, payload, **kw):
            captured["stored_summary"] = payload.summary

    summ = _ResumeSummarizer()
    monkeypatch.setattr(sds, "SessionExtractService", lambda: _Store())

    await sds.distill_transcript(
        tmp_path / "s1.jsonl",
        summarizer=summ,
        embedder=None,
        storage_backend=None,
        project_root=str(tmp_path),
    )

    # Exactly ONE generate() call — distil the new slice; the merge is no-LLM (2b-2).
    assert len(summ.calls) == 1
    # Only NEW turns were sent to the distil call (not OLD-A/OLD-B).
    distil_prompt = summ.calls[0]
    assert "NEW-C" in distil_prompt and "NEW-D" in distil_prompt
    assert "OLD-A" not in distil_prompt and "OLD-B" not in distil_prompt
    # Structural merge preserves BOTH the prior summary ("old") and the new one.
    assert "old" in captured["stored_summary"]
    assert "new only" in captured["stored_summary"]
    # Sidecar advanced to the new last offset.
    offset, _ = sds.read_progress(str(tmp_path), "s1")
    assert offset == 3


# ---------------------------------------------------------------------------
# Task 5: guardrail — fresh path produces exactly one generate() call (no merge)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fresh_path_no_merge_call_and_payload_is_run_extraction_output(
    tmp_path, monkeypatch
):
    from brainpalace_server.indexing.session_loader import Turn

    meta = _meta("s9")
    turns = [Turn(0, "user", "text", "A"), Turn(1, "assistant", "text", "B")]
    monkeypatch.setattr(sds, "parse_transcript", lambda p: (meta, turns))

    captured = {}

    class _FreshSummarizer:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt):
            self.calls.append(prompt)
            return '{"summary": "fresh", "decisions": [], "triplets": []}'

    class _FreshStore:
        async def store(self, payload, **kw):
            captured["summary"] = payload.summary

    summ = _FreshSummarizer()
    monkeypatch.setattr(sds, "SessionExtractService", lambda: _FreshStore())

    await sds.distill_transcript(
        tmp_path / "s9.jsonl",
        summarizer=summ,
        embedder=None,
        storage_backend=None,
        project_root=str(tmp_path),
    )
    assert len(summ.calls) == 1  # no merge call on a fresh session
    assert captured["summary"] == "fresh"
    assert not any("Merge these" in c for c in summ.calls)


def test_non_terminal_turns_are_not_distilled():
    """A step still in flight must be skipped, then picked up once when done."""
    from brainpalace_server.indexing.session_loader import Turn
    from brainpalace_server.services.session_distill_service import (
        select_new_turns,
    )

    turns = [
        Turn(0, "user", "text", "a"),
        Turn(1, "assistant", "text", "b", terminal=False),
        Turn(2, "assistant", "text", "c"),
    ]

    selected = select_new_turns(turns, prior_offset=-1)

    assert [t.index for t in selected] == [0, 2]


def test_offset_is_the_max_terminal_index_not_the_last_position():
    from brainpalace_server.indexing.session_loader import Turn
    from brainpalace_server.services.session_distill_service import (
        resume_offset_for,
    )

    turns = [
        Turn(0, "user", "text", "a"),
        Turn(7, "assistant", "text", "b"),
        Turn(9, "assistant", "text", "c", terminal=False),
    ]

    # 9 is still running, so the durable high-water mark is 7.
    assert resume_offset_for(turns) == 7


def test_offset_never_advances_past_an_in_flight_middle_step():
    """A RUNNING step with DONE steps after it (antigravity mutates statuses in
    place — the antigravity fixture has exactly this shape: step 3 RUNNING while
    4-9 are DONE) must gate the offset, or its finished form is skipped forever.
    Post-gap terminal turns may be re-selected later; merge is a union, loss is
    not recoverable."""
    from brainpalace_server.indexing.session_loader import Turn
    from brainpalace_server.services.session_distill_service import (
        resume_offset_for,
    )

    turns = [
        Turn(0, "user", "text", "a"),
        Turn(3, "assistant", "text", "b", terminal=False),
        Turn(4, "assistant", "text", "c"),
        Turn(5, "assistant", "text", "d"),
    ]

    assert resume_offset_for(turns) == 0


def test_resume_offset_of_empty_transcript_is_minus_one():
    from brainpalace_server.services.session_distill_service import (
        resume_offset_for,
    )

    assert resume_offset_for([]) == -1


def test_select_new_turns_respects_prior_offset():
    from brainpalace_server.indexing.session_loader import Turn
    from brainpalace_server.services.session_distill_service import (
        select_new_turns,
    )

    turns = [Turn(i, "assistant", "text", str(i)) for i in range(5)]
    selected = select_new_turns(turns, prior_offset=2)
    assert [t.index for t in selected] == [3, 4]

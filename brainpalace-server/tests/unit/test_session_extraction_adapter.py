import pytest

from brainpalace_server.services.session_extraction_adapter import (
    SessionExtractionAdapter,
)


class _FakeDistiller:
    def __init__(self):
        self.calls = []

    async def maybe_distill(self, path, *, newer_exists=False, force=False):
        self.calls.append(str(path))
        return object() if "good" in str(path) else None


@pytest.mark.asyncio
async def test_select_and_process_delegate_to_distiller(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "brainpalace_server.services.session_extraction_adapter.pending_sessions",
        lambda *a, **k: [("s1", "/x/good.jsonl"), ("s2", "/x/bad.jsonl")],
    )
    dist = _FakeDistiller()
    ad = SessionExtractionAdapter(
        distiller=dist, project_root=str(tmp_path), archive_dir=str(tmp_path)
    )
    items = await ad.select_pending(10)
    assert items == ["/x/good.jsonl", "/x/bad.jsonl"]
    assert await ad.process("/x/good.jsonl") is True
    assert await ad.process("/x/bad.jsonl") is False


@pytest.mark.asyncio
async def test_select_pending_uses_distiller_idle_seconds(tmp_path, monkeypatch):
    # 2-7: selection must use the SAME quiescence threshold as distillation, so a
    # not-yet-quiescent session isn't selected and then deferred (miscounted as a
    # drain failure that burns a max_count slot).
    captured: dict = {}

    def fake_pending(project_root, archive_dir, **kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(
        "brainpalace_server.services.session_extraction_adapter.pending_sessions",
        fake_pending,
    )

    class _D:
        idle_seconds = 99

        async def maybe_distill(self, *a, **k):
            return None

    ad = SessionExtractionAdapter(
        distiller=_D(), project_root=str(tmp_path), archive_dir=str(tmp_path)
    )
    await ad.select_pending(10)
    assert captured.get("idle_seconds") == 99


@pytest.mark.asyncio
async def test_not_ready_without_distiller(tmp_path):
    ad = SessionExtractionAdapter(
        distiller=None, project_root=str(tmp_path), archive_dir=str(tmp_path)
    )
    assert ad.is_ready is False

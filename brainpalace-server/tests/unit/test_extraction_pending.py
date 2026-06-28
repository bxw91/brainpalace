from brainpalace_server.storage.extraction_pending import DocPendingStore


def _store(tmp_path):
    return DocPendingStore(tmp_path / "extraction_pending.db")


def test_mark_select_done_roundtrip(tmp_path):
    s = _store(tmp_path)
    s.mark_pending("c1", "alpha")
    s.mark_pending("c2", "beta")
    assert s.count_pending() == 2
    batch = s.select_pending(10)
    assert batch == [("c1", "alpha"), ("c2", "beta")]  # FIFO
    s.mark_done("c1")
    assert s.count_pending() == 1
    assert s.select_pending(10) == [("c2", "beta")]


def test_select_respects_limit(tmp_path):
    s = _store(tmp_path)
    for i in range(5):
        s.mark_pending(f"c{i}", f"t{i}")
    assert len(s.select_pending(2)) == 2


def test_remark_same_hash_is_noop_but_changed_hash_requeues(tmp_path):
    s = _store(tmp_path)
    s.mark_pending("c1", "original")
    s.mark_done("c1")
    assert s.count_pending() == 0
    s.mark_pending("c1", "original")  # unchanged content ⇒ stays done
    assert s.count_pending() == 0
    s.mark_pending("c1", "EDITED")  # changed content ⇒ re-queue
    assert s.select_pending(10) == [("c1", "EDITED")]

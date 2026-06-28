from brainpalace_server.models.extraction_api import (
    ExtractionSubmit,
    PendingBatch,
    PendingItem,
    SubmitResult,
    TripletIn,
)


def test_pending_item_doc_and_session_shapes():
    doc = PendingItem(source="doc", id="c1", text="hello")
    sess = PendingItem(source="session", id="s1", path="/a/s1.jsonl")
    assert doc.text == "hello" and doc.path is None
    assert sess.path == "/a/s1.jsonl" and sess.text is None


def test_pending_batch():
    b = PendingBatch(
        items=[PendingItem(source="doc", id="c1", text="t")], doc_pending_total=5
    )
    assert b.doc_pending_total == 5 and len(b.items) == 1


def test_extraction_submit_doc():
    s = ExtractionSubmit(
        source="doc",
        chunk_id="c1",
        triplets=[TripletIn(subject="A", predicate="uses", object="B")],
    )
    assert s.source == "doc" and s.triplets[0].subject == "A"


def test_submit_result():
    assert (
        SubmitResult(
            source="doc", id="c1", triplets_stored=2, marked_done=True
        ).triplets_stored
        == 2
    )

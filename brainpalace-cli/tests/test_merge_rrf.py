from brainpalace_cli.merge import rrf_merge


def _r(cid, score=1.0):
    return {"chunk_id": cid, "text": f"t-{cid}", "source": f"s-{cid}", "score": score}


def test_interleaves_by_rank_not_score():
    a = [("me", [_r("a1", 99.0), _r("a2", 98.0)])]
    b = [("shared", [_r("b1", 0.3), _r("b2", 0.2)])]
    out = rrf_merge(a + b, top_k=4)
    # rank-1 items from both instances outrank rank-2 items, regardless of raw score
    top2 = {r["chunk_id"] for r in out[:2]}
    assert top2 == {"a1", "b1"}


def test_results_tagged_with_instance():
    out = rrf_merge([("me", [_r("x")])])
    assert out[0]["instance"] == "me"


def test_duplicate_chunk_ids_merge_and_boost():
    out = rrf_merge([("me", [_r("dup"), _r("a2")]), ("shared", [_r("dup")])], top_k=3)
    assert out[0]["chunk_id"] == "dup"  # appears in both -> highest fused score
    assert len([r for r in out if r["chunk_id"] == "dup"]) == 1


def test_top_k_respected():
    many = [("me", [_r(f"c{i}") for i in range(20)])]
    assert len(rrf_merge(many, top_k=5)) == 5

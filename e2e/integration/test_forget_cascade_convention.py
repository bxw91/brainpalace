"""Full-forget cascade convention (Round 4 Stage 3, D2) — pinned.

``DELETE /ingest/source/{source_id}`` is, by convention, the full-forget
entry point: one caller-supplied ``source_id`` seeded across all three
ingest tiers (document chunks, typed records, lazy-tier references) is
dropped from all of them in one call, with per-tier counts in the response.
``DELETE /ingest/text/{source_id}`` keeps its narrower, published
chunks-only meaning (pinned by ``test_share_receive_convention.py``) —
unaffected by this cascade.

This test drives the exact CLI surface (``brainpalace ingest`` /
``ingest record`` / ``ingest reference`` / ``ingest --forget``) against a
live server, exactly like the share-receive convention test, so no
direct-HTTP helper is introduced.

Skip-gated on ``OPENAI_API_KEY`` via the shared ``cli`` fixture chain
(``cli`` -> ``server_process`` -> ``check_api_key``), exactly like the other
e2e integration tests — collected but skipped when no key is present.
"""

import pytest

SOURCE_ID = "forget-cascade-001"
DOMAIN = "home"
DOC_SOURCE = "forget-cascade-scanner"
EXPECTED_DOC_SOURCE = f"ingest://{DOMAIN}/{DOC_SOURCE}/{SOURCE_ID}"
DOC_TEXT = "Racun za forget cascade test, iznos 42 eura"
UNIQUE_METRIC = "forgetcascadetestmetric"
UNIQUE_POINTER = "file:///forget-cascade/receipt.pdf"


@pytest.fixture
def doc_file(tmp_path):
    path = tmp_path / "forget-cascade.txt"
    path.write_text(DOC_TEXT, encoding="utf-8")
    return path


def _doc_hits(query_json: dict) -> list[dict]:
    results = (query_json or {}).get("results", []) or []
    return [r for r in results if r.get("source") == EXPECTED_DOC_SOURCE]


def _refs_with_pointer(refs_json: dict) -> list[dict]:
    refs = (refs_json or {}).get("references", []) or []
    return [r for r in refs if r.get("pointer") == UNIQUE_POINTER]


def test_forget_cascade_drops_all_three_tiers(cli, doc_file):
    # 1. Seed the document tier (chunks).
    ingest_doc = cli.run(
        "ingest",
        str(doc_file),
        "--domain",
        DOMAIN,
        "--source",
        DOC_SOURCE,
        "--source-id",
        SOURCE_ID,
        "--json",
    )
    assert ingest_doc["returncode"] == 0, ingest_doc

    # 2. Seed the record tier (eager, typed) under the SAME source_id.
    ingest_record = cli.run(
        "ingest",
        "record",
        "--subject",
        "forget-cascade-test-subject",
        "--metric",
        UNIQUE_METRIC,
        "--value",
        "42",
        "--domain",
        DOMAIN,
        "--source",
        DOC_SOURCE,
        "--source-id",
        SOURCE_ID,
        "--json",
    )
    assert ingest_record["returncode"] == 0, ingest_record

    # 3. Seed the reference tier (lazy pointer + summary) under the SAME
    #    source_id.
    ingest_reference = cli.run(
        "ingest",
        "reference",
        "--pointer",
        UNIQUE_POINTER,
        "--summary",
        "forget cascade test receipt",
        "--domain",
        DOMAIN,
        "--source",
        DOC_SOURCE,
        "--source-id",
        SOURCE_ID,
        "--json",
    )
    assert ingest_reference["returncode"] == 0, ingest_reference

    # 4. All three tiers are discoverable before the forget.
    doc_found = cli.query_raw(
        "racun forget cascade", mode="bm25", top_k=10, threshold=0.0
    )
    assert doc_found["returncode"] == 0, doc_found
    assert _doc_hits(doc_found["json"]), doc_found["json"]

    stats_before = cli.run("records", "stats", "--json")
    assert stats_before["returncode"] == 0, stats_before
    assert UNIQUE_METRIC in (stats_before["json"] or {}).get("metrics", [])

    refs_before = cli.run("references", "list", "--domain", DOMAIN, "--json")
    assert refs_before["returncode"] == 0, refs_before
    assert _refs_with_pointer(refs_before["json"]), refs_before["json"]

    # 5. Full forget — one call, all three tiers.
    forget = cli.run("ingest", "--forget", "--source-id", SOURCE_ID, "--json")
    assert forget["returncode"] == 0, forget
    assert forget["json"]["records_deleted"] == 1, forget["json"]
    assert forget["json"]["references_deleted"] == 1, forget["json"]
    assert forget["json"]["chunks_deleted"] >= 1, forget["json"]

    # 6. All three tiers are gone.
    doc_after = cli.query_raw(
        "racun forget cascade", mode="bm25", top_k=10, threshold=0.0
    )
    assert doc_after["returncode"] == 0, doc_after
    assert not _doc_hits(doc_after["json"]), doc_after["json"]

    stats_after = cli.run("records", "stats", "--json")
    assert stats_after["returncode"] == 0, stats_after
    assert UNIQUE_METRIC not in (stats_after["json"] or {}).get("metrics", [])

    refs_after = cli.run("references", "list", "--domain", DOMAIN, "--json")
    assert refs_after["returncode"] == 0, refs_after
    assert not _refs_with_pointer(refs_after["json"]), refs_after["json"]


def test_delete_text_endpoint_unaffected_by_cascade(cli, doc_file):
    """DELETE /ingest/text/{source_id} (the pinned share-convention path)
    keeps its narrow chunks-only meaning — seeding a record/reference under
    the same source_id and un-ingesting via --delete leaves them intact."""
    source_id = "forget-cascade-002"
    metric = "forgetcascadetextonlymetric"
    pointer = "file:///forget-cascade/textonly.pdf"

    cli.run(
        "ingest",
        str(doc_file),
        "--domain",
        DOMAIN,
        "--source",
        DOC_SOURCE,
        "--source-id",
        source_id,
        "--json",
    )
    cli.run(
        "ingest",
        "record",
        "--subject",
        "forget-cascade-test-subject",
        "--metric",
        metric,
        "--value",
        "1",
        "--domain",
        DOMAIN,
        "--source",
        DOC_SOURCE,
        "--source-id",
        source_id,
        "--json",
    )
    cli.run(
        "ingest",
        "reference",
        "--pointer",
        pointer,
        "--summary",
        "text-only delete test",
        "--domain",
        DOMAIN,
        "--source",
        DOC_SOURCE,
        "--source-id",
        source_id,
        "--json",
    )

    deleted = cli.run("ingest", "--delete", "--source-id", source_id, "--json")
    assert deleted["returncode"] == 0, deleted

    stats_after = cli.run("records", "stats", "--json")
    assert metric in (stats_after["json"] or {}).get("metrics", [])

    refs_after = cli.run("references", "list", "--domain", DOMAIN, "--json")
    assert any(
        r.get("pointer") == pointer
        for r in (refs_after["json"] or {}).get("references", [])
    )

    # Cleanup: use the cascade endpoint so this test doesn't leak state.
    cli.run("ingest", "--forget", "--source-id", source_id, "--json")

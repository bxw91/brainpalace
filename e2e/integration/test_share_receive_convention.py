"""Share-receive convention (household multi-instance M1, spec R2-2) — pinned.

A "received share" is, by convention, an ``/ingest/text`` write with:
``domain="shared"``, ``source="shared-from:<person>"``, a sender-scoped
``source_id``, ``shared_by``/``shared_at`` metadata, and the sender's
sensitivity. Retract-on-TTL is the consumer scheduling
``DELETE /ingest/text/{source_id}`` (engine half shipped in Round 1).

This test pins that the convention round-trips end-to-end against a live
server: ingest a share -> it is discoverable under its ``shared-from``
provenance source -> delete it -> it is gone. It drives the exact HTTP
endpoints through the suite's ``CLIRunner`` (the ``brainpalace ingest`` /
``ingest --delete`` commands wrap ``POST``/``DELETE /ingest/text``), so no
direct-HTTP helper is introduced.

Skip-gated on ``OPENAI_API_KEY`` via the shared ``cli`` fixture chain
(``cli`` -> ``server_process`` -> ``check_api_key``), exactly like the other
e2e integration tests — collected but skipped when no key is present.
"""

import pytest

SHARED_SOURCE_ID = "marko-share-001"
EXPECTED_SOURCE = "ingest://shared/shared-from:marko/marko-share-001"
SHARE_TEXT = "Marko ti je podijelio: ugovor o najmu, istice 2026-09-01"


@pytest.fixture
def share_file(tmp_path):
    """Write the share body to a temp file the CLI can read (no stdin plumbing)."""
    path = tmp_path / "share.txt"
    path.write_text(SHARE_TEXT, encoding="utf-8")
    return path


def _shared_hits(query_json: dict) -> list[dict]:
    results = (query_json or {}).get("results", []) or []
    return [r for r in results if r.get("source") == EXPECTED_SOURCE]


def test_share_round_trip(cli, share_file):
    # 1. Ingest as a share (POST /ingest/text) with the pinned provenance shape.
    ingest = cli.run(
        "ingest",
        str(share_file),
        "--domain",
        "shared",
        "--source",
        "shared-from:marko",
        "--source-id",
        SHARED_SOURCE_ID,
        "--metadata",
        "shared_by=marko",
        "--metadata",
        "shared_at=2026-07-06T10:00:00Z",
        "--sensitivity",
        "normal",
        "--language",
        "hr",
        "--json",
    )
    assert ingest["returncode"] == 0, ingest

    # 2. The share is discoverable under its shared-from provenance source.
    found = cli.query_raw(
        "ugovor najam", mode="bm25", language="hr", top_k=10, threshold=0.0
    )
    assert found["returncode"] == 0, found
    assert _shared_hits(found["json"]), found["json"]

    # 3. Retract: DELETE /ingest/text/{source_id}.
    deleted = cli.run("ingest", "--delete", "--source-id", SHARED_SOURCE_ID, "--json")
    assert deleted["returncode"] == 0, deleted

    # 4. The same query no longer returns the shared hit.
    after = cli.query_raw(
        "ugovor najam", mode="bm25", language="hr", top_k=10, threshold=0.0
    )
    assert after["returncode"] == 0, after
    assert not _shared_hits(after["json"]), after["json"]

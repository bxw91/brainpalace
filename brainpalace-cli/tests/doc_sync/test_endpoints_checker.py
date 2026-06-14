from brainpalace_cli.doc_sync.checkers.endpoints import EndpointsChecker
from brainpalace_cli.doc_sync.facts import InterfaceSnapshot

SNAP = InterfaceSnapshot(1, "9.9.9", endpoints=["/health", "/runtime", "/query"])


def test_dangling_endpoint_flagged(tmp_path):
    (tmp_path / "API_REFERENCE.md").write_text("`GET /gone` and `GET /health`\n")
    recs = EndpointsChecker(doc_roots=[tmp_path]).check(SNAP)
    bad = {r.source_id for r in recs}
    assert "/gone" in bad and "/health" not in bad


def test_valid_endpoints_clean(tmp_path):
    (tmp_path / "API_REFERENCE.md").write_text("`GET /health` `POST /query`\n")
    assert EndpointsChecker(doc_roots=[tmp_path]).check(SNAP) == []

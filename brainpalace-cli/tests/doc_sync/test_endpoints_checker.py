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


def test_dashboard_refs_skipped_when_dashboard_absent(tmp_path):
    # No `/dashboard` routes in the snapshot → dashboard not introspected (CI
    # without the dashboard package) → its references are unverifiable, not drift.
    (tmp_path / "API_REFERENCE.md").write_text("`GET /dashboard/api/events`\n")
    assert EndpointsChecker(doc_roots=[tmp_path]).check(SNAP) == []


def test_dashboard_refs_gated_when_dashboard_present(tmp_path):
    # Snapshot has dashboard routes → dashboard was introspected → a doc pointing
    # at a non-existent dashboard route is real drift.
    snap = InterfaceSnapshot(1, "9.9.9", endpoints=["/health", "/dashboard/api/events"])
    (tmp_path / "API_REFERENCE.md").write_text(
        "`GET /dashboard/api/events` `GET /dashboard/api/gone`\n"
    )
    bad = {r.source_id for r in EndpointsChecker(doc_roots=[tmp_path]).check(snap)}
    assert bad == {"/dashboard/api/gone"}

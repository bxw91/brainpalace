# brainpalace-cli/tests/doc_sync/test_base_checker.py
from brainpalace_cli.doc_sync.checkers.base import diff_sets
from brainpalace_cli.doc_sync.facts import DriftKind


def test_diff_sets_reports_missing_extra_clean():
    live = {"index", "query", "status"}
    docs = {"index", "query", "OLD"}
    records = diff_sets(
        surface="cli", live=live, docs=docs, doc_path_for=lambda s: f"{s}.md"
    )
    kinds = {(r.source_id, r.kind) for r in records}
    assert ("status", DriftKind.MISSING) in kinds  # live, no doc
    assert ("OLD", DriftKind.EXTRA) in kinds  # doc, not live
    assert all(r.source_id != "index" for r in records)  # matched → no record

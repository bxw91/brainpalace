from brainpalace_cli.doc_sync import contract_parity
from brainpalace_cli.doc_sync.checkers.mode_parity_checker import ModeParityChecker
from brainpalace_cli.doc_sync.facts import DriftKind, InterfaceSnapshot


def _snap():
    return InterfaceSnapshot(schema_version=1, source_version="test")


def test_clean_tree_yields_no_records():
    assert ModeParityChecker().check(_snap()) == []


def test_injected_drift_yields_named_record(monkeypatch):
    def fake():
        return [
            contract_parity.ParityMismatch(
                "query_modes", "mcp_literal", missing=frozenset({"timeline"})
            )
        ]

    monkeypatch.setattr(
        "brainpalace_cli.doc_sync.checkers.mode_parity_checker."
        "query_modes_mismatches",
        fake,
    )
    (rec,) = ModeParityChecker().check(_snap())
    assert rec.kind == DriftKind.MISMATCH
    assert "mcp_literal" in rec.detail and "timeline" in rec.detail

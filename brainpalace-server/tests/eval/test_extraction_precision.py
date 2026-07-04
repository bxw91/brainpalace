"""Plan E — deterministic extraction eval (no LLM, no API key).

Layer 1: precision/recall of the pure AST extractor against a reviewed
manifest over tests/eval/corpus/*.py — a regression alarm for extractor edits.
Layer 2: the extracted triples written into a real SQLite store must answer
path/impact queries (the Plan E reads) end to end.
"""

import json
from pathlib import Path

from brainpalace_server.indexing.code_symbol_extractor import extract_python_symbols
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore

CORPUS = Path(__file__).parent / "corpus"
MANIFEST = Path(__file__).parent / "expected_code_triplets.json"


def _extracted(name: str) -> set[tuple[str, str, str]]:
    f = CORPUS / name
    root = str(CORPUS.resolve()).replace("\\", "/")
    fp = str(f.resolve()).replace("\\", "/")
    res = extract_python_symbols(fp, f.read_text(), root=root)
    return {
        (
            t.effective_subject_id.replace(root, "<ROOT>"),
            t.predicate,
            t.effective_object_id.replace(root, "<ROOT>"),
        )
        for t in res.triples
    }


def test_precision_and_recall_are_exact():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest, "manifest is empty — regenerate it (Task 9 Step 1)"
    for name, expected_rows in manifest.items():
        expected = {tuple(r) for r in expected_rows}
        got = _extracted(name)
        fp = got - expected  # precision failures
        fn = expected - got  # recall failures
        precision = 1 - len(fp) / max(len(got), 1)
        recall = 1 - len(fn) / max(len(expected), 1)
        assert precision == 1.0 and recall == 1.0, (
            f"{name}: precision={precision:.3f} recall={recall:.3f}\n"
            f"unexpected={sorted(fp)[:5]}\nmissing={sorted(fn)[:5]}"
        )


class _TripleNode:
    def __init__(self, id, name, label):
        self.id = id
        self.name = name
        self.label = label
        self.properties = {}
        self.domain = "code"


class _TripleRel:
    def __init__(self, source_id, target_id, label):
        self.source_id = source_id
        self.target_id = target_id
        self.label = label
        self.properties = {}


def _build_store_from_corpus(tmp_path) -> SQLitePropertyGraphStore:
    s = SQLitePropertyGraphStore(str(tmp_path / "eval.db"))
    root = str(CORPUS.resolve()).replace("\\", "/")
    for f in sorted(CORPUS.glob("*.py")):
        fp = str(f.resolve()).replace("\\", "/")
        res = extract_python_symbols(fp, f.read_text(), root=root)
        for t in res.triples:
            sid, oid = t.effective_subject_id, t.effective_object_id
            s.upsert_nodes(
                [
                    _TripleNode(
                        sid, t.subject_name or t.subject, t.subject_type or "Entity"
                    ),
                    _TripleNode(
                        oid, t.object_name or t.object, t.object_type or "Entity"
                    ),
                ]
            )
            s.upsert_relations([_TripleRel(sid, oid, t.predicate)])
    return s


def test_store_answers_path_and_impact_on_corpus(tmp_path):
    s = _build_store_from_corpus(tmp_path)
    root = str(CORPUS.resolve()).replace("\\", "/")
    invoices = f"{root}/invoices.py"
    # Every corpus file must exist as a File node with at least one edge.
    assert s.get_node(invoices) is not None
    # A symbol defined in invoices.py reaches the file in one hop, and the
    # file's impact set contains that symbol (reverse defined_in).
    imp = s.impact(invoices, max_depth=1)
    assert imp, "invoices.py has no dependents — extractor wrote no defined_in?"
    symbol_id = imp[0]["id"]
    paths = s.find_paths(symbol_id, invoices)
    assert paths["paths"] and paths["paths"][0]["length"] == 1

"""Eval: Croatian recall improvement + English no-regression.

Two-armed test that uses ``BM25IndexManager`` directly (no server, no embeddings,
no OpenAI key required) to prove that:

1. **Croatian recall arm** — indexing Croatian docs with ``default_lang="hr"``
   achieves a measurably higher top-1 hit-rate than ``default_lang="en"`` on
   queries whose surface forms differ from the document forms (inflection).
   The Croatian stemmer reduces both forms to the same root; English
   tokenisation does not.

2. **English no-regression arm** — the English queries in the fixture achieve
   at least the observed baseline hit-rate (>=0.80) when the index uses
   ``default_lang="en"``.  This guards against the Croatian analyser changes
   accidentally breaking English retrieval.

Fixture: ``tests/eval/fixtures/croatian_corpus.json``
Schema documented in that file's ``_comment`` field.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from llama_index.core.schema import TextNode

from brainpalace_server.indexing.bm25_index import BM25IndexManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "croatian_corpus.json"

# English no-regression threshold.  Set from an observed run: en_hit_rate was
# 1.00 on the five English queries; threshold placed at 0.80 to allow one miss
# without failing while still catching a catastrophic regression.
EN_BASELINE = 0.80


def _load_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _node(doc: dict) -> TextNode:
    """Build a TextNode from a fixture doc dict."""
    return TextNode(
        text=doc["text"],
        id_=doc["id"],
        metadata={"text_language": doc["lang"], "source_type": "doc"},
    )


def _build_manager(tmp_path: Path, lang: str) -> BM25IndexManager:
    return BM25IndexManager(
        persist_dir=str(tmp_path / lang),
        default_lang=lang,
        engine="stem",
    )


def _hit_rate(manager: BM25IndexManager, queries: list[dict]) -> float:
    """Top-1 hit-rate: fraction of queries where the top result is relevant."""
    if not queries:
        return 0.0
    hits = 0
    for q in queries:
        results = asyncio.run(manager.search_with_filters(q["query"], top_k=1))
        if results and results[0].node.node_id in q["relevant"]:
            hits += 1
    return hits / len(queries)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_croatian_recall_beats_english_default(tmp_path: Path) -> None:
    """Croatian queries retrieve correct docs better with hr analyser than en."""
    data = _load_fixture()

    hr_docs = [d for d in data["docs"] if d["lang"] == "hr"]
    hr_queries = [q for q in data["queries"] if q["lang"] == "hr"]

    nodes = [_node(d) for d in hr_docs]

    # Build hr-language index
    mgr_hr = _build_manager(tmp_path, "hr")
    mgr_hr.build_index(nodes)

    # Build en-language index over the same Croatian docs
    mgr_en = _build_manager(tmp_path, "en")
    mgr_en.build_index(nodes)

    hr_hit_rate = _hit_rate(mgr_hr, hr_queries)
    en_hit_rate = _hit_rate(mgr_en, hr_queries)

    print(
        f"\nCroatian arm — hr analyser hit-rate: {hr_hit_rate:.2f}, "
        f"en analyser hit-rate: {en_hit_rate:.2f} "
        f"(n={len(hr_queries)} queries)"
    )

    # Croatian-aware stemming must measurably outperform English tokenisation
    # on inflected Croatian queries.
    assert hr_hit_rate > en_hit_rate, (
        f"Expected Croatian analyzer (hr_hit_rate={hr_hit_rate:.2f}) to beat "
        f"English default (en_hit_rate={en_hit_rate:.2f}) on Croatian inflections"
    )


def test_english_no_regression(tmp_path: Path) -> None:
    """English retrieval stays at or above the observed baseline with en analyser."""
    data = _load_fixture()

    en_docs = [d for d in data["docs"] if d["lang"] == "en"]
    en_queries = [q for q in data["queries"] if q["lang"] == "en"]

    nodes = [_node(d) for d in en_docs]

    mgr = _build_manager(tmp_path, "en")
    mgr.build_index(nodes)

    en_hit_rate = _hit_rate(mgr, en_queries)

    print(
        f"\nEnglish no-regression — hit-rate: {en_hit_rate:.2f} "
        f"(threshold={EN_BASELINE}, n={len(en_queries)} queries)"
    )

    assert en_hit_rate >= EN_BASELINE, (
        f"English retrieval regressed: hit-rate={en_hit_rate:.2f} "
        f"< baseline threshold={EN_BASELINE}"
    )

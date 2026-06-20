"""Tests for the doc-dep settle: two drains (structural + cleanness) assign each
doc-dep claim SUPPORTED / PENDING / UNVERIFIABLE with zero agent involvement."""

from __future__ import annotations

import json

import pytest

import brainpalace_cli.commands.verify_docs as vd


@pytest.fixture
def record_env(tmp_path, monkeypatch):
    """Isolate _record_verdicts end-to-end: temp cache + needs-human report, captured
    re-stamps. Each test sets its own _REPO_ROOT and _audited_doc_set."""
    monkeypatch.setattr(vd, "_VERDICT_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(vd, "_NEEDS_HUMAN_REPORT", tmp_path / "needs-human.md")
    stamped: list[str] = []
    monkeypatch.setattr(vd, "_restamp", lambda docs: stamped.extend(docs) or list(docs))
    return stamped


def _code(doc, claim, verdict="SUPPORTED"):
    return {
        "doc": doc,
        "claim": claim,
        "grounding": "x.py",
        "grounding_tier": "code",
        "raw_verdict": verdict,
        "verdict": verdict,
    }


def _dep(doc, claim, deps, raw="SUPPORTED"):
    return {
        "doc": doc,
        "claim": claim,
        "grounding": " ".join(deps),
        "grounding_tier": "doc-dep",
        "raw_verdict": raw,
        "verdict": raw,
        "grounding_files": list(deps),
    }


def _settle(recs):
    cache = {f"h{i}": r for i, r in enumerate(recs)}
    stuck = vd._settle(cache)
    by_claim = {r["claim"]: r["verdict"] for r in cache.values()}
    return by_claim, stuck


def test_clean_cascade_confirms_dependent() -> None:
    # D code-clean; C in E depends on D -> SUPPORTED
    by, stuck = _settle(
        [_code("docs/D.md", "d"), _dep("docs/E.md", "c", ["docs/D.md"])]
    )
    assert by["c"] == "SUPPORTED"
    assert stuck == []


def test_pending_when_dependency_not_yet_clean() -> None:
    # D has an open UNVERIFIABLE (not clean) but is code-groundable (structurally OK)
    recs = [
        _code("docs/D.md", "d1"),
        _code("docs/D.md", "d2", "UNVERIFIABLE"),
        _dep("docs/E.md", "c", ["docs/D.md"]),
    ]
    by, stuck = _settle(recs)
    assert by["c"] == "PENDING"  # reachable but not clean
    assert stuck == []


def test_transient_contradicted_upstream_is_pending_not_unverifiable() -> None:
    # D code-grounded but currently CONTRADICTED -> structurally resolvable -> C PENDING
    recs = [
        _code("docs/D.md", "d", "CONTRADICTED"),
        _dep("docs/E.md", "c", ["docs/D.md"]),
    ]
    by, stuck = _settle(recs)
    assert by["c"] == "PENDING"
    assert stuck == []


def test_cycle_is_unverifiable() -> None:
    # E depends on F, F depends on E, neither has a code claim -> stuck -> UNVERIFIABLE
    recs = [
        _dep("docs/E.md", "ce", ["docs/F.md"]),
        _dep("docs/F.md", "cf", ["docs/E.md"]),
    ]
    by, stuck = _settle(recs)
    assert by["ce"] == "UNVERIFIABLE"
    assert by["cf"] == "UNVERIFIABLE"
    assert set(stuck) == {"docs/E.md", "docs/F.md"}


def test_orphan_dependency_is_unverifiable() -> None:
    # C depends on G; G has only a doc-dep on a missing/never-code doc H (orphan)
    recs = [
        _dep("docs/E.md", "c", ["docs/G.md"]),
        _dep("docs/G.md", "g", ["docs/H.md"]),
    ]
    by, stuck = _settle(recs)
    assert by["c"] == "UNVERIFIABLE"
    assert by["g"] == "UNVERIFIABLE"


def test_doc_dep_contradicted_raw_stays_contradicted() -> None:
    # C itself is wrong against D -> raw CONTRADICTED is never gated
    by, stuck = _settle(
        [
            _code("docs/D.md", "d"),
            _dep("docs/E.md", "c", ["docs/D.md"], raw="CONTRADICTED"),
        ]
    )
    assert by["c"] == "CONTRADICTED"


def test_chain_converges_in_one_settle() -> None:
    # code D -> E(dep D) -> F(dep E): all SUPPORTED in a single settle pass
    recs = [
        _code("docs/D.md", "d"),
        _dep("docs/E.md", "e", ["docs/D.md"]),
        _dep("docs/F.md", "f", ["docs/E.md"]),
    ]
    by, stuck = _settle(recs)
    assert by["e"] == "SUPPORTED" and by["f"] == "SUPPORTED"


def test_needs_human_report_written_when_stuck_and_all_judged(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_NEEDS_HUMAN_REPORT", tmp_path / "needs-human.md")
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/E.md", "docs/F.md"})
    monkeypatch.setattr(vd, "_is_excluded", lambda p: False)
    cache = {
        "h1": {
            "doc": "docs/E.md",
            "claim": "ce",
            "grounding_tier": "doc-dep",
            "raw_verdict": "SUPPORTED",
            "verdict": "UNVERIFIABLE",
            "grounding_files": ["docs/F.md"],
        },
        "h2": {
            "doc": "docs/F.md",
            "claim": "cf",
            "grounding_tier": "doc-dep",
            "raw_verdict": "SUPPORTED",
            "verdict": "UNVERIFIABLE",
            "grounding_files": ["docs/E.md"],
        },
    }
    reported = vd._refresh_needs_human_report(cache, ["docs/E.md", "docs/F.md"])
    assert set(reported) == {"docs/E.md", "docs/F.md"}
    assert vd._NEEDS_HUMAN_REPORT.exists()
    assert "docs/E.md" in vd._NEEDS_HUMAN_REPORT.read_text()


def test_needs_human_report_deleted_when_not_stuck(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_NEEDS_HUMAN_REPORT", tmp_path / "needs-human.md")
    vd._NEEDS_HUMAN_REPORT.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/E.md"})
    monkeypatch.setattr(vd, "_is_excluded", lambda p: False)
    cache = {"h1": {"doc": "docs/E.md", "claim": "c", "verdict": "SUPPORTED"}}
    assert vd._refresh_needs_human_report(cache, []) == []
    assert not vd._NEEDS_HUMAN_REPORT.exists()


def test_needs_human_report_held_while_unjudged_docs_remain(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_NEEDS_HUMAN_REPORT", tmp_path / "needs-human.md")
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/E.md", "docs/UNSEEN.md"})
    monkeypatch.setattr(vd, "_is_excluded", lambda p: False)
    cache = {
        "h1": {
            "doc": "docs/E.md",
            "claim": "c",
            "verdict": "UNVERIFIABLE",
            "grounding_tier": "doc-dep",
            "raw_verdict": "SUPPORTED",
            "grounding_files": ["docs/X.md"],
        }
    }
    # UNSEEN.md not yet judged -> hold, don't cry deadlock
    assert vd._refresh_needs_human_report(cache, ["docs/E.md"]) == []
    assert not vd._NEEDS_HUMAN_REPORT.exists()


def test_e2e_dependent_confirms_then_pending_on_upstream_drift(
    record_env, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/D.md", "docs/E.md"})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "D.md").write_text("# D\nbody\n", encoding="utf-8")
    (tmp_path / "docs" / "E.md").write_text("# E\nbody\n", encoding="utf-8")
    (tmp_path / "x.py").write_text("a=1\n", encoding="utf-8")
    # Run 1: D code-clean, E depends on D -> C SUPPORTED
    vd._record_verdicts(
        {
            "verdicts": [
                {
                    "doc": "docs/D.md",
                    "claim": "d",
                    "grounding": "x.py",
                    "verdict": "SUPPORTED",
                    "grounding_files": ["x.py"],
                },
                {
                    "doc": "docs/E.md",
                    "claim": "c",
                    "grounding": "docs/D.md",
                    "verdict": "SUPPORTED",
                },
            ]
        }
    )
    recs = {
        r["claim"]: r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r
    }
    assert recs["c"]["verdict"] == "SUPPORTED"
    # Run 2: D now CONTRADICTED (upstream drift); E NOT in payload.
    vd._record_verdicts(
        {
            "verdicts": [
                {
                    "doc": "docs/D.md",
                    "claim": "d",
                    "grounding": "x.py",
                    "verdict": "CONTRADICTED",
                    "grounding_files": ["x.py"],
                },
            ]
        }
    )
    recs = {
        r["claim"]: r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r
    }
    # settle scanned the whole cache: C demoted SUPPORTED->PENDING with NO agent pass
    assert recs["c"]["verdict"] == "PENDING"
    assert recs["c"]["raw_verdict"] == "SUPPORTED"  # raw untouched (no re-ground)


def test_e2e_pending_doc_not_restamped(record_env, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/D.md", "docs/E.md"})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "D.md").write_text("# D\nbody\n", encoding="utf-8")
    (tmp_path / "docs" / "E.md").write_text("# E\nbody\n", encoding="utf-8")
    # D never code-grounded clean -> E's claim is PENDING -> E not in `clean`
    summary = vd._record_verdicts(
        {
            "verdicts": [
                {
                    "doc": "docs/D.md",
                    "claim": "d",
                    "grounding": "docs/E.md",
                    "verdict": "SUPPORTED",
                },
                {
                    "doc": "docs/E.md",
                    "claim": "c",
                    "grounding": "docs/D.md",
                    "verdict": "SUPPORTED",
                },
            ]
        }
    )
    # cycle E<->D, no code -> both UNVERIFIABLE, neither clean
    assert summary["clean"] == []
    assert summary["restamped"] == []

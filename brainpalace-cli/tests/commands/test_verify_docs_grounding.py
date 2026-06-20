"""Tests for the `verify-docs` code-first grounding + dependency machinery.

Covers the hardening that keeps Layer B honest:
  * `_is_excluded` / exclusion of historical/frozen/scratch material,
  * `_grounding_tier` — fail-CLOSED classification (only a real source path earns
    the trusted `code` tier; unknown `.md`, excluded docs, and empty/vague grounding
    never do),
  * `_record_verdicts` — coercion of mis-labeled SUPPORTED + the audited-doc guard,
  * `_order_by_cost` — smallest-prose-first ordering,
  * cache integrity — atomic save + loud abort on a corrupt cache.
"""

from __future__ import annotations

import json

import pytest

import brainpalace_cli.commands.verify_docs as vd

AUDITED = {"docs/A.md", "docs/B.md", "docs/INSTALL.md", "README.md"}


# --- exclusion ------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rel, excluded",
    [
        ("docs/CHANGELOG.md", True),
        ("docs/ORIGINAL_SPEC.md", True),
        ("docs/superpowers/specs/x.md", True),
        (".planning/notes.md", True),
        ("docs/INSTALL.md", False),
        ("README.md", False),
        ("brainpalace_cli/cli.py", False),
    ],
)
def test_is_excluded(rel: str, excluded: bool) -> None:
    assert vd._is_excluded(rel) is excluded


# --- the core invariant: verify-set == grounding-valid-set ----------------- #


def test_verify_set_equals_grounding_valid_set() -> None:
    """Only code confirms a claim — no doc tier confirms.
    Every audited doc is in the audited set; none gets the `code` tier when named
    as a grounding source (they all yield `doc`). This locks the two concepts so a
    future tier change can't silently let a doc ground a claim as SUPPORTED."""
    audited = vd._audited_doc_set()
    # With every audited doc treated as clean, a doc named as grounding source must
    # NOT return `code` — it should return `doc`. Only real source paths return `code`.
    for d in audited:
        tier = vd._grounding_tier(d, audited, audited)
        assert tier != "code", f"{d!r} should not be `code` tier"


def test_non_project_docs_are_in_neither_group() -> None:
    """Excluded / unknown docs are neither verified nor groundable as code."""
    audited = vd._audited_doc_set()
    for nd in (
        "docs/superpowers/specs/x.md",
        ".planning/p.md",
        "docs/CHANGELOG.md",
        "docs/ORIGINAL_SPEC.md",
        "random/notes.md",
    ):
        assert nd not in audited  # not verified
        # Under code-only-confirms these land in `doc`/`unresolved`, never `code`
        assert vd._grounding_tier(nd, audited, audited) != "code"


# --- grounding tier (fail-closed truth table) ------------------------------ #


@pytest.mark.parametrize(
    "grounding, expected",
    [
        ("brainpalace_server/storage/schema.py", "code"),
        ("server.py: CREATE INDEX ...", "code"),
        ("src/x.py (see docs/A.md)", "code"),  # code wins
        ("docs/A.md", "doc-dep"),  # audited doc → dependency
        ("docs/B.md", "doc-dep"),
        ("docs/CHANGELOG.md", "unresolved"),  # excluded → never clean
        ("docs/NONEXISTENT.md", "unresolved"),  # unknown .md → never clean
        (".planning/foo.md", "unresolved"),  # excluded prefix
        ("", "unresolved"),
        ("see the docs", "unresolved"),
    ],
)
def test_grounding_tier(grounding: str, expected: str) -> None:
    assert vd._grounding_tier(grounding, AUDITED, {"docs/A.md"}) == expected


def test_grounding_tier_self_reference_is_unresolved() -> None:
    """A claim grounded ONLY on its own doc is not a dependency — a doc can't ground its
    own claim — so it is `unresolved` (eligible for the audit tier when audit-fresh),
    `doc-dep`. A different audited doc is still a real dependency."""
    assert (
        vd._grounding_tier("docs/A.md", AUDITED, set(), doc="docs/A.md") == "unresolved"
    )
    assert vd._grounding_tier("docs/B.md", AUDITED, set(), doc="docs/A.md") == "doc-dep"


def test_grounding_tier_absolute_path_is_stripped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    g = f"{tmp_path}/docs/CHANGELOG.md"  # excluded → never clean → unresolved
    assert vd._grounding_tier(g, AUDITED, set()) == "unresolved"


# --- record + coercion + guard --------------------------------------------- #


@pytest.fixture
def record_env(tmp_path, monkeypatch):
    """Isolate _record_verdicts: temp cache/report, fixed audited set, no real
    doc/manifest writes (capture what _restamp is asked to stamp instead)."""
    monkeypatch.setattr(vd, "_VERDICT_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(vd, "_NEEDS_HUMAN_REPORT", tmp_path / "needs-human.md")
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: set(AUDITED))
    # Default: no doc is audit-fresh, so an `unresolved` claim coerces to UNVERIFIABLE
    # (the pre-audit-tier behavior). Tests exercising audit-tier promotion override it.
    monkeypatch.setattr(vd, "_doc_audit_fresh", lambda doc: False)
    stamped: list[str] = []
    monkeypatch.setattr(vd, "_restamp", lambda docs: stamped.extend(docs) or list(docs))
    return stamped


def test_record_coerces_by_tier(record_env) -> None:
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "c1",
                "grounding": "src/x.py",
                "verdict": "SUPPORTED",
            },
            {
                "doc": "docs/INSTALL.md",
                "claim": "c2",
                "grounding": "docs/B.md",
                "verdict": "SUPPORTED",
            },  # doc-dep, dep has no records → settle → UNVERIFIABLE (orphan)
            {
                "doc": "docs/INSTALL.md",
                "claim": "c3",
                "grounding": "docs/CHANGELOG.md",
                "verdict": "SUPPORTED",
            },  # excluded → UNVERIFIABLE
            {
                "doc": "docs/INSTALL.md",
                "claim": "c4",
                "grounding": "",
                "verdict": "SUPPORTED",
            },  # unresolved → UNVERIFIABLE
        ]
    }
    summary = vd._record_verdicts(payload)
    by_claim = {
        r["claim"]: r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r
    }
    assert by_claim["c1"]["verdict"] == "SUPPORTED"
    assert by_claim["c2"]["verdict"] == "UNVERIFIABLE"  # doc grounding never confirms
    assert by_claim["c3"]["verdict"] == "UNVERIFIABLE"
    assert by_claim["c4"]["verdict"] == "UNVERIFIABLE"
    # Doc has open items → not clean → not re-stamped.
    assert summary["restamped"] == []


def test_record_drops_non_audited_and_excluded(record_env) -> None:
    payload = {
        "verdicts": [
            {
                "doc": "docs/CHANGELOG.md",
                "claim": "x",
                "grounding": "src/x.py",
                "verdict": "SUPPORTED",
            },  # excluded doc → dropped
            {
                "doc": "docs/superpowers/p.md",
                "claim": "y",
                "grounding": "src/x.py",
                "verdict": "SUPPORTED",
            },  # non-audited → dropped
            {
                "doc": "some/random.md",
                "claim": "z",
                "grounding": "src/x.py",
                "verdict": "SUPPORTED",
            },  # non-audited → dropped
        ]
    }
    vd._record_verdicts(payload)
    cached = [
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r
    ]
    assert cached == []  # nothing recorded


def test_record_restamps_only_fully_code_clean_doc(record_env) -> None:
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "ok",
                "grounding": "src/x.py",
                "verdict": "SUPPORTED",
            },
        ]
    }
    summary = vd._record_verdicts(payload)
    assert summary["restamped"] == ["docs/INSTALL.md"]
    assert record_env == ["docs/INSTALL.md"]


# --- durable human-confirm ledger ------------------------------------------ #


@pytest.fixture
def confirm_env(record_env, tmp_path, monkeypatch):
    """record_env + an isolated, durable confirm ledger. `_doc_audit_fresh` stays
    False (inherited) so any SUPPORTED on an unresolved claim can ONLY come from the
    confirm ledger — proving the order is what vouched, not a manifest stamp."""
    monkeypatch.setattr(vd, "_CONFIRMED_LEDGER", tmp_path / "confirmed.json")
    return record_env


def _unresolved_payload() -> dict:
    # Empty grounding → tier `unresolved`; not audit-fresh → coerced UNVERIFIABLE.
    return {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "OpenAI keys start with sk-",
                "grounding": "",
                "verdict": "SUPPORTED",
            }
        ]
    }


def _cache_claims() -> dict:
    return {
        r["claim"]: r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r
    }


def test_confirm_promotes_unresolved_to_audit_supported(confirm_env) -> None:
    vd._record_verdicts(_unresolved_payload())
    assert _cache_claims()["OpenAI keys start with sk-"]["verdict"] == "UNVERIFIABLE"

    result = vd._confirm_claims(["docs/INSTALL.md"])
    assert [c["claim"] for c in result["confirmed"]] == ["OpenAI keys start with sk-"]
    rec = _cache_claims()["OpenAI keys start with sk-"]
    assert rec["verdict"] == "SUPPORTED"
    assert rec["grounding_tier"] == "audit"
    # The order is persisted durably, keyed by claim hash.
    ledger = json.loads(vd._CONFIRMED_LEDGER.read_text())
    assert any(v["claim"] == "OpenAI keys start with sk-" for v in ledger.values())


def test_confirm_order_survives_a_later_record_sweep(confirm_env) -> None:
    """A re-record (the agent re-judges UNVERIFIABLE) must NOT erase the standing
    order — the claim stays SUPPORTED because the durable ledger is re-consulted."""
    vd._record_verdicts(_unresolved_payload())
    vd._confirm_claims(["docs/INSTALL.md"])
    # Agent sweeps again and re-submits its raw UNVERIFIABLE judgment.
    vd._record_verdicts(_unresolved_payload())
    rec = _cache_claims()["OpenAI keys start with sk-"]
    assert rec["verdict"] == "SUPPORTED"
    assert rec["grounding_tier"] == "audit"


def test_confirm_refuses_code_grounded_claim(confirm_env) -> None:
    """Code is ground truth: a code-tier claim cannot be human-vouched. It must be
    re-prosed to drop the code referent first."""
    vd._record_verdicts(
        {
            "verdicts": [
                {
                    "doc": "docs/INSTALL.md",
                    "claim": "k1=1.5",
                    "grounding": "src/bm25.py",
                    "verdict": "UNVERIFIABLE",
                }
            ]
        }
    )
    result = vd._confirm_claims(["docs/INSTALL.md"])
    assert result["confirmed"] == []
    assert [r["claim"] for r in result["refused"]] == ["k1=1.5"]
    # Nothing written to the durable ledger.
    assert not vd._CONFIRMED_LEDGER.exists()


# --- classify-or-refuse (new doc surface) ---------------------------------- #


def test_filter_unclassified_drops_sweep_keeps_explicit() -> None:
    """A glob-matched doc absent from the manifest is unclassified: dropped from a
    sweep, but kept when named explicitly (naming = classifying it as a real doc).
    A manifest-known doc is always kept."""
    manifest = {"docs/KNOWN.md": "hash"}
    entries = [
        {"path": "docs/KNOWN.md", "trigger": "all"},  # classified → kept
        {"path": "docs/SCRATCH.md", "trigger": "all"},  # unclassified sweep → drop
        {"path": "docs/NEW.md", "trigger": "explicit"},  # named → kept
    ]
    kept, unclassified = vd._filter_unclassified(entries, manifest)
    assert [e["path"] for e in kept] == ["docs/KNOWN.md", "docs/NEW.md"]
    assert unclassified == ["docs/SCRATCH.md"]


# --- ordering -------------------------------------------------------------- #


def test_order_by_cost_smallest_prose_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "big.md").write_text("# big\n" + "x " * 500, encoding="utf-8")
    (tmp_path / "small.md").write_text("# small\n", encoding="utf-8")
    (tmp_path / "mid.md").write_text("# mid\n" + "y " * 50, encoding="utf-8")
    entries = [{"path": p} for p in ("big.md", "small.md", "mid.md")]
    ordered = [e["path"] for e in vd._order_by_cost(entries)]
    assert ordered == ["small.md", "mid.md", "big.md"]


def test_order_by_cost_unreadable_sorts_last(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "real.md").write_text("# real\nbody\n", encoding="utf-8")
    entries = [{"path": "missing.md"}, {"path": "real.md"}]
    ordered = [e["path"] for e in vd._order_by_cost(entries)]
    assert ordered == ["real.md", "missing.md"]


# --- progress stats -------------------------------------------------------- #


def test_verification_stats_counts_full_partial_none() -> None:
    audited = {"docs/A.md", "docs/B.md", "docs/C.md", "docs/D.md"}
    cache = {
        # A fully verified (all SUPPORTED)
        "a": {"doc": "docs/A.md", "verdict": "SUPPORTED"},
        # B partial (judged but has an open item)
        "b1": {"doc": "docs/B.md", "verdict": "SUPPORTED"},
        "b2": {"doc": "docs/B.md", "verdict": "PENDING"},
        # C partial (a contradiction)
        "c": {"doc": "docs/C.md", "verdict": "CONTRADICTED"},
        # D never judged → "none"
        # a stale row for a doc no longer audited → ignored
        "x": {"doc": "docs/GONE.md", "verdict": "SUPPORTED"},
    }
    stats = vd._verification_stats(cache, audited)
    assert stats == {"total": 4, "full": 1, "partial": 2, "none": 1}
    # counts always partition the total
    assert stats["full"] + stats["partial"] + stats["none"] == stats["total"]


# --- server pre-flight (restart-or-fail) ----------------------------------- #


def test_ensure_server_up_reachable_no_restart(monkeypatch) -> None:
    """Already up → True, and no restart is attempted."""
    monkeypatch.setattr(vd, "_server_reachable", lambda url: True)
    calls: list = []
    monkeypatch.setattr(vd.subprocess, "run", lambda *a, **k: calls.append(a))
    assert vd._ensure_server_up(None) is True
    assert calls == []


def test_ensure_server_up_restart_succeeds(monkeypatch) -> None:
    """Down, then up after the restart attempt → True."""
    import time

    states = iter([False, True])  # initial down → reachable on first poll
    monkeypatch.setattr(vd, "_server_reachable", lambda url: next(states))
    ran: list = []
    monkeypatch.setattr(vd.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    assert vd._ensure_server_up(None) is True
    assert ran  # a restart was attempted


def test_ensure_server_up_restart_fails(monkeypatch) -> None:
    """Stays unreachable through the restart + polling → False (caller stops)."""
    import time

    monkeypatch.setattr(vd, "_server_reachable", lambda url: False)
    monkeypatch.setattr(vd.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    assert vd._ensure_server_up(None) is False


# --- cache integrity ------------------------------------------------------- #


def test_save_cache_is_atomic_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_VERDICT_CACHE", tmp_path / "c.json")
    vd._save_cache({"h1": {"doc": "docs/A.md", "verdict": "SUPPORTED"}})
    assert vd._load_cache() == {"h1": {"doc": "docs/A.md", "verdict": "SUPPORTED"}}
    # no leftover temp files in the dir
    assert [p.name for p in tmp_path.iterdir()] == ["c.json"]


def test_load_missing_cache_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_VERDICT_CACHE", tmp_path / "nope.json")
    assert vd._load_cache() == {}


def test_load_corrupt_cache_aborts_and_backs_up(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "c.json"
    cache.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(vd, "_VERDICT_CACHE", cache)
    with pytest.raises(SystemExit):
        vd._load_cache()
    # corrupt file moved aside, not silently dropped
    assert (tmp_path / "c.corrupt").exists()
    assert not cache.exists()


def test_record_stores_grounding_relation(record_env, tmp_path, monkeypatch) -> None:
    """A code-grounded verdict carrying grounding_files gets grounding_files +
    grounding_hash (combined file content hash) recorded."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "x.py").write_text("TOOL_REGISTRY = {}\n", encoding="utf-8")
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "c",
                "grounding": "x.py",
                "grounding_files": ["x.py"],
                "verdict": "SUPPORTED",
            }
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "c"
    )
    assert rec["grounding_files"] == ["x.py"]
    assert rec["grounding_hash"] == vd._relation_hash(["x.py"])


def test_record_derives_relation_from_grounding_when_files_omitted(
    record_env, tmp_path, monkeypatch
) -> None:
    """When the agent omits grounding_files, the relation is derived from the code
    path in the grounding string."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "x.py").write_text("code\n", encoding="utf-8")
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "c",
                "grounding": "x.py: snippet",
                "verdict": "SUPPORTED",
            }
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "c"
    )
    assert rec["grounding_files"] == ["x.py"]
    assert rec["grounding_hash"] == vd._relation_hash(["x.py"])


def test_record_does_not_store_relation_for_doc_grounding(
    record_env, tmp_path, monkeypatch
) -> None:
    """A doc-grounded claim (coerced UNVERIFIABLE) carries no code relation."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "c",
                "grounding": "docs/A.md",
                "grounding_files": ["docs/A.md"],
                "verdict": "SUPPORTED",
            }
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "c"
    )
    assert "grounding_hash" not in rec
    assert "grounding_files" not in rec


def test_record_prunes_orphan_claims_for_a_doc(
    record_env, tmp_path, monkeypatch
) -> None:
    """Re-recording a doc REPLACES its records — a claim the doc no longer makes is
    dropped, so cache-driven skip never re-verifies a doc for a deleted claim."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "x.py").write_text("code\n", encoding="utf-8")
    first = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "old",
                "grounding": "x.py",
                "verdict": "SUPPORTED",
            },
        ]
    }
    vd._record_verdicts(first)
    second = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "new",
                "grounding": "x.py",
                "verdict": "SUPPORTED",
            },
        ]
    }
    vd._record_verdicts(second)
    claims = {
        r["claim"]
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r and r.get("doc") == "docs/INSTALL.md"
    }
    assert claims == {"new"}  # "old" pruned


def test_record_doc_dep_stores_raw_verdict_and_dep_relation(
    record_env, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/E.md", "docs/D.md"})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "D.md").write_text("# D\nbody\n", encoding="utf-8")
    payload = {
        "verdicts": [
            {
                "doc": "docs/E.md",
                "claim": "rests on D",
                "grounding": "docs/D.md",
                "verdict": "SUPPORTED",
            },
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "rests on D"
    )
    assert rec["grounding_tier"] == "doc-dep"
    assert rec["raw_verdict"] == "SUPPORTED"
    assert rec["grounding_files"] == ["docs/D.md"]
    assert rec["grounding_hash"] == vd._relation_hash(["docs/D.md"])


def test_record_doc_dep_contradicted_keeps_raw(
    record_env, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/E.md", "docs/D.md"})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "D.md").write_text("# D\nbody\n", encoding="utf-8")
    payload = {
        "verdicts": [
            {
                "doc": "docs/E.md",
                "claim": "wrong",
                "grounding": "docs/D.md",
                "verdict": "CONTRADICTED",
            },
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "wrong"
    )
    assert rec["raw_verdict"] == "CONTRADICTED"


def test_record_unresolved_doc_still_coerces_unverifiable(
    record_env, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: {"docs/E.md"})
    (tmp_path / "docs").mkdir()
    payload = {
        "verdicts": [
            {
                "doc": "docs/E.md",
                "claim": "c",
                "grounding": "docs/CHANGELOG.md",
                "verdict": "SUPPORTED",
            },
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "c"
    )
    assert rec["verdict"] == "UNVERIFIABLE"
    assert "grounding_files" not in rec


# --- audit tier (human-vouched external claim, no code referent) ----------- #


def test_doc_audit_fresh_matches_manifest(tmp_path, monkeypatch) -> None:
    """True only while the freshness-manifest hash equals the doc's CURRENT body."""
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "X.md"
    doc.write_text("# X\nbody v1\n", encoding="utf-8")

    class _Fresh:
        @staticmethod
        def content_hash(content: str) -> str:
            return "H:" + content.strip()

        @staticmethod
        def load_manifest() -> dict:
            return {"docs/X.md": "H:# X\nbody v1"}

    monkeypatch.setattr(vd, "_freshness", lambda: _Fresh)
    assert vd._doc_audit_fresh("docs/X.md") is True
    # Edit the body without re-auditing → hash mismatch → not fresh (fails closed).
    doc.write_text("# X\nbody v2\n", encoding="utf-8")
    assert vd._doc_audit_fresh("docs/X.md") is False


def test_doc_audit_fresh_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    assert vd._doc_audit_fresh("docs/GONE.md") is False


def test_record_unresolved_audit_tier_when_fresh(record_env, monkeypatch) -> None:
    """An `unresolved` claim (no code, no audited-doc dep) in an audit-FRESH doc is
    recorded as the `audit` SOURCE tier with verdict SUPPORTED (status) — asserted,
    vouched by the stamp, clean, so the doc re-stamps. The verdict enum gains nothing:
    provenance lives on `grounding_tier`, not the status."""
    monkeypatch.setattr(vd, "_doc_audit_fresh", lambda doc: True)
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "~50ms for 100 candidates",
                "grounding": "",
                "verdict": "UNVERIFIABLE",
            },
        ]
    }
    summary = vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "~50ms for 100 candidates"
    )
    assert rec["verdict"] == "SUPPORTED"  # status
    assert rec["raw_verdict"] == "SUPPORTED"
    assert rec["grounding_tier"] == "audit"  # source
    assert "grounding_files" not in rec  # no code relation by design
    assert summary["restamped"] == ["docs/INSTALL.md"]
    assert summary["audit_grounded"] == 1


def test_record_unresolved_unverifiable_when_not_audit_fresh(record_env) -> None:
    """Same claim in a NOT-audit-fresh doc stays UNVERIFIABLE (record_env default) —
    nobody vouched for the current body, so it surfaces (no laundering)."""
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "~50ms for 100 candidates",
                "grounding": "",
                "verdict": "UNVERIFIABLE",
            },
        ]
    }
    summary = vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "~50ms for 100 candidates"
    )
    assert rec["verdict"] == "UNVERIFIABLE"
    assert summary["restamped"] == []


def test_record_unresolved_supported_kept_via_audit_when_fresh(
    record_env, monkeypatch
) -> None:
    """A SUPPORTED `unresolved` claim is no longer blindly coerced to UNVERIFIABLE in an
    audit-fresh doc — it stays SUPPORTED on the `audit` source tier."""
    monkeypatch.setattr(vd, "_doc_audit_fresh", lambda doc: True)
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "c",
                "grounding": "",
                "verdict": "SUPPORTED",
            },
        ]
    }
    vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "c"
    )
    assert rec["verdict"] == "SUPPORTED"
    assert rec["grounding_tier"] == "audit"


def test_record_self_ref_grounding_becomes_audit_when_fresh(
    record_env, monkeypatch
) -> None:
    """A claim grounded on its OWN doc (self-reference) in an audit-fresh doc lands
    on the `audit` tier / SUPPORTED — the self-ref is not a doc-dep, so promotion fires
    (regression guard: this previously mis-tiered as doc-dep → orphan UNVERIFIABLE)."""
    monkeypatch.setattr(vd, "_doc_audit_fresh", lambda doc: True)
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "~50ms for 100 candidates",
                "grounding": "docs/INSTALL.md",
                "verdict": "UNVERIFIABLE",
            },
        ]
    }
    summary = vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "~50ms for 100 candidates"
    )
    assert rec["grounding_tier"] == "audit"
    assert rec["verdict"] == "SUPPORTED"
    assert summary["restamped"] == ["docs/INSTALL.md"]


def test_record_unresolved_contradicted_never_promoted(record_env, monkeypatch) -> None:
    """A CONTRADICTED `unresolved` claim is real drift — never laundered to audit tier
    even in an audit-fresh doc."""
    monkeypatch.setattr(vd, "_doc_audit_fresh", lambda doc: True)
    payload = {
        "verdicts": [
            {
                "doc": "docs/INSTALL.md",
                "claim": "wrong",
                "grounding": "",
                "verdict": "CONTRADICTED",
            },
        ]
    }
    summary = vd._record_verdicts(payload)
    rec = next(
        r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and r.get("claim") == "wrong"
    )
    assert rec["verdict"] == "CONTRADICTED"
    assert summary["restamped"] == []


def test_audit_tier_supported_is_clean() -> None:
    """An audit-tier claim is recorded SUPPORTED, so it is clean like any other
    SUPPORTED — the source tier doesn't affect cleanliness, only provenance."""
    cache = {
        "h1": {"doc": "docs/A.md", "verdict": "SUPPORTED", "grounding_tier": "audit"},
        "h2": {"doc": "docs/B.md", "verdict": "SUPPORTED", "grounding_tier": "code"},
    }
    clean = vd._clean_verified_docs(cache)
    assert "docs/A.md" in clean
    assert "docs/B.md" in clean


def test_audit_grounded_count_in_report() -> None:
    """Audit-tier claims are clean (SUPPORTED, no open items) but surfaced as a one-line
    count so the human sees how much of 'clean' rests on human assertion vs code."""
    summary = {
        "per_doc": {
            "docs/A.md": {
                "SUPPORTED": [{"claim": "~50ms", "evidence": ""}],
                "CONTRADICTED": [],
                "UNVERIFIABLE": [],
                "PENDING": [],
            },
        },
        "restamped": ["docs/A.md"],
        "audit_grounded": 1,
    }
    out = vd._render_report(summary)
    assert "0 open item" in out  # audit-tier is not an open item
    assert "1 claim(s) grounded by human audit" in out


def test_pending_blocks_clean(monkeypatch) -> None:
    cache = {
        "h1": {"doc": "docs/E.md", "verdict": "PENDING"},
        "h2": {"doc": "docs/F.md", "verdict": "SUPPORTED"},
    }
    clean = vd._clean_verified_docs(cache)
    assert "docs/E.md" not in clean  # PENDING is not clean
    assert "docs/F.md" in clean


def test_pending_silent_in_drift_report() -> None:
    summary = {
        "per_doc": {
            "docs/E.md": {
                "SUPPORTED": [],
                "CONTRADICTED": [],
                "UNVERIFIABLE": [],
                "PENDING": [{"claim": "p", "evidence": ""}],
            },
        },
        "restamped": [],
    }
    out = vd._render_report(summary)
    assert "PENDING" not in out  # silent
    assert "0 open item" in out


# --- resettle (deterministic re-settle, no LLM) ---------------------------- #


def _seed(records: dict) -> None:
    vd._VERDICT_CACHE.write_text(json.dumps(records), encoding="utf-8")


def _by_claim() -> dict:
    return {
        r["claim"]: r
        for r in json.loads(vd._VERDICT_CACHE.read_text()).values()
        if isinstance(r, dict) and "claim" in r
    }


def test_resettle_reclassifies_self_ref_to_audit(record_env, monkeypatch) -> None:
    # Old buggy state: a self-referential grounding cached as a doc-dep UNVERIFIABLE.
    # The host doc is now audit-fresh → resettle re-derives it as audit/SUPPORTED,
    # replaying the FIXED raw verdict — no agent/LLM involved.
    monkeypatch.setattr(vd, "_doc_audit_fresh", lambda doc: doc == "docs/INSTALL.md")
    _seed(
        {
            "legacy-key": {
                "doc": "docs/INSTALL.md",
                "claim": "external fact",
                "grounding": "docs/INSTALL.md",  # self-reference
                "raw_verdict": "SUPPORTED",
                "verdict": "UNVERIFIABLE",
                "grounding_tier": "doc-dep",
                "evidence": "",
            }
        }
    )
    summary = vd._resettle()
    rec = _by_claim()["external fact"]
    assert rec["grounding_tier"] == "audit"
    assert rec["verdict"] == "SUPPORTED"
    # Outcome changed AND the doc is now clean → re-stamped (only this doc).
    assert summary["restamped"] == ["docs/INSTALL.md"]
    assert record_env == ["docs/INSTALL.md"]


def test_resettle_no_change_does_not_restamp(record_env) -> None:
    _seed(
        {
            "h1": {
                "doc": "docs/INSTALL.md",
                "claim": "code claim",
                "grounding": "src/x.py",
                "raw_verdict": "SUPPORTED",
                "verdict": "SUPPORTED",
                "grounding_tier": "code",
                "evidence": "",
            }
        }
    )
    summary = vd._resettle()
    rec = _by_claim()["code claim"]
    assert (rec["verdict"], rec["grounding_tier"]) == ("SUPPORTED", "code")
    assert summary["restamped"] == []  # nothing moved → no re-stamp, no date churn
    assert record_env == []


def test_resettle_keeps_contradicted_open(record_env) -> None:
    _seed(
        {
            "h1": {
                "doc": "docs/INSTALL.md",
                "claim": "broken claim",
                "grounding": "src/x.py",
                "raw_verdict": "CONTRADICTED",
                "verdict": "CONTRADICTED",
                "grounding_tier": "code",
                "evidence": "drifted",
            }
        }
    )
    summary = vd._resettle()
    assert _by_claim()["broken claim"]["verdict"] == "CONTRADICTED"
    assert summary["restamped"] == []  # not clean → never stamped
    out = vd._render_report(summary)
    assert "[CONTRADICTED] broken claim" in out


def test_resettle_settles_doc_dep_when_dependency_clean(
    record_env, monkeypatch, tmp_path
) -> None:
    # docs/A.md is code-clean; docs/INSTALL.md has a doc-dep claim on it that was
    # cached PENDING (dep not yet clean). Resettle must settle it SUPPORTED — and
    # re-stamp ONLY INSTALL (the doc that changed), not the already-clean A.
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "A.md").write_text("# A\nbody\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
    _seed(
        {
            "a1": {
                "doc": "docs/A.md",
                "claim": "a code claim",
                "grounding": "src/x.py",
                "raw_verdict": "SUPPORTED",
                "verdict": "SUPPORTED",
                "grounding_tier": "code",
                "evidence": "",
            },
            "i1": {
                "doc": "docs/INSTALL.md",
                "claim": "rests on A",
                "grounding": "docs/A.md",
                "raw_verdict": "SUPPORTED",
                "verdict": "PENDING",  # stale: was waiting on A
                "grounding_tier": "doc-dep",
                "grounding_files": ["docs/A.md"],
                "grounding_hash": "stale",
                "evidence": "",
            },
        }
    )
    summary = vd._resettle()
    by = _by_claim()
    assert by["rests on A"]["verdict"] == "SUPPORTED"
    assert by["a code claim"]["verdict"] == "SUPPORTED"
    # Scoped re-stamp: only the doc whose outcome moved.
    assert summary["restamped"] == ["docs/INSTALL.md"]
    assert "docs/A.md" not in summary["restamped"]


def test_resettle_prunes_deaudited_doc(record_env) -> None:
    _seed(
        {
            "g1": {
                "doc": "docs/GONE.md",  # not in AUDITED
                "claim": "orphan",
                "grounding": "src/x.py",
                "raw_verdict": "SUPPORTED",
                "verdict": "SUPPORTED",
                "grounding_tier": "code",
                "evidence": "",
            }
        }
    )
    vd._resettle()
    assert "orphan" not in _by_claim()  # pruned from the cache

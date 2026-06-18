"""Tests for the `verify-docs` code-first grounding + dependency machinery.

Covers the hardening that keeps Layer B honest:
  * `_is_excluded` / exclusion of historical/frozen/scratch material,
  * `_grounding_tier` — fail-CLOSED classification (only a real source path earns
    the trusted `code` tier; unknown `.md`, excluded docs, and empty/vague grounding
    never do),
  * `_record_verdicts` — coercion of mis-labeled SUPPORTED + the audited-doc guard,
  * `_filter_blocked` — defer a doc until its dependency verifies,
  * `_deadlocked_docs` — cross-dependent cycle detection vs. drainable chains,
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
    """A doc may be VERIFIED iff it may be a GROUNDING SOURCE: both are the single
    `_audited_doc_set()` (real project docs). No non-project doc is in either group.
    This locks the two concepts to one set so a future tier change can't silently
    let a non-audited doc ground a claim."""
    audited = vd._audited_doc_set()
    # With every audited doc treated as clean, a doc is a valid grounding source iff
    # its tier is a doc tier (verified/unverified) — i.e. iff it is in the audited
    # set. Anything else classifies as excluded/unresolved and cannot ground.
    grounding_valid = {
        d
        for d in audited
        if vd._grounding_tier(d, audited, audited) in ("verified-doc", "unverified-doc")
    }
    assert grounding_valid == audited


def test_non_project_docs_are_in_neither_group() -> None:
    """Excluded / unknown docs are neither verified nor groundable."""
    audited = vd._audited_doc_set()
    for nd in (
        "docs/superpowers/specs/x.md",
        ".planning/p.md",
        "docs/CHANGELOG.md",
        "docs/ORIGINAL_SPEC.md",
        "random/notes.md",
    ):
        assert nd not in audited  # not verified
        assert vd._grounding_tier(nd, audited, audited) not in (
            "verified-doc",
            "unverified-doc",
        )  # not groundable


# --- grounding tier (fail-closed truth table) ------------------------------ #


@pytest.mark.parametrize(
    "grounding, expected",
    [
        # real source paths → the only trusted tier
        ("brainpalace_server/storage/schema.py", "code"),
        ("server.py: CREATE INDEX ...", "code"),
        # code wins even alongside an incidental doc mention
        ("src/x.py (see docs/CHANGELOG.md)", "code"),
        # audited docs, by clean-ness
        ("docs/A.md", "verified-doc"),
        ("docs/B.md", "unverified-doc"),
        # excluded / historical / scratch → never grounds
        ("docs/CHANGELOG.md", "excluded-doc"),
        ("docs/ORIGINAL_SPEC.md", "excluded-doc"),
        ("docs/superpowers/specs/x.md", "excluded-doc"),
        (".planning/foo.md", "excluded-doc"),
        # an unknown .md path is doc-shaped → ungroundable, NOT code
        ("docs/NONEXISTENT.md", "excluded-doc"),
        # empty / vague → no evidence path at all
        ("", "unresolved"),
        ("see the docs", "unresolved"),
    ],
)
def test_grounding_tier(grounding: str, expected: str) -> None:
    clean = {"docs/A.md"}  # A is clean, B is not
    assert vd._grounding_tier(grounding, AUDITED, clean) == expected


def test_grounding_tier_absolute_path_is_stripped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    g = f"{tmp_path}/docs/CHANGELOG.md"
    assert vd._grounding_tier(g, AUDITED, set()) == "excluded-doc"


# --- record + coercion + guard --------------------------------------------- #


@pytest.fixture
def record_env(tmp_path, monkeypatch):
    """Isolate _record_verdicts: temp cache/report, fixed audited set, no real
    doc/manifest writes (capture what _restamp is asked to stamp instead)."""
    monkeypatch.setattr(vd, "_VERDICT_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(vd, "_BLOCKED_REPORT", tmp_path / "blocked.md")
    monkeypatch.setattr(vd, "_audited_doc_set", lambda: set(AUDITED))
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
            },  # unverified doc → BLOCKED
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
    assert by_claim["c2"]["verdict"] == "BLOCKED"
    assert by_claim["c2"]["blocked_on"] == ["docs/B.md"]
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


# --- defer scheduler ------------------------------------------------------- #


def test_filter_blocked_defers_until_dependency_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vd, "_REPO_ROOT", tmp_path)
    fresh = vd._freshness()

    def doc(name: str) -> str:
        body = f"# {name}\nprose {name}\n"
        (tmp_path / name).write_text(body, encoding="utf-8")
        return body

    bodies = {
        n: doc(n)
        for n in (
            "dep_open.md",
            "dep_clean.md",
            "edited.md",
            "with_drift.md",
            "explicit.md",
        )
    }
    manifest = {n: fresh.content_hash(b) for n, b in bodies.items()}
    manifest["edited.md"] = "stale-hash"  # simulate edit since judging
    monkeypatch.setattr(fresh, "load_manifest", lambda: manifest)

    # dep.md is the dependency: clean so dependents on it re-activate.
    cache = {
        # blocked on an OPEN dep, unchanged → DEFERRED
        "h1": {"doc": "dep_open.md", "verdict": "BLOCKED", "blocked_on": ["X.md"]},
        # blocked on a CLEAN dep → re-activates (kept)
        "h2": {"doc": "dep_clean.md", "verdict": "BLOCKED", "blocked_on": ["clean.md"]},
        "hc": {"doc": "clean.md", "verdict": "SUPPORTED"},
        # blocked but edited (hash mismatch) → kept
        "h3": {"doc": "edited.md", "verdict": "BLOCKED", "blocked_on": ["X.md"]},
        # blocked AND has real drift → kept (needs surfacing)
        "h4": {"doc": "with_drift.md", "verdict": "BLOCKED", "blocked_on": ["X.md"]},
        "h4b": {"doc": "with_drift.md", "verdict": "CONTRADICTED"},
        # blocked but explicitly requested → kept
        "h5": {"doc": "explicit.md", "verdict": "BLOCKED", "blocked_on": ["X.md"]},
    }
    entries = [
        {"path": "dep_open.md", "trigger": "all"},
        {"path": "dep_clean.md", "trigger": "all"},
        {"path": "edited.md", "trigger": "all"},
        {"path": "with_drift.md", "trigger": "all"},
        {"path": "explicit.md", "trigger": "explicit"},
    ]
    kept, deferred = vd._filter_blocked(entries, cache)
    assert deferred == ["dep_open.md"]
    assert {e["path"] for e in kept} == {
        "dep_clean.md",
        "edited.md",
        "with_drift.md",
        "explicit.md",
    }


# --- deadlock detection ---------------------------------------------------- #


def test_deadlocked_docs_cycle_vs_drain() -> None:
    cache = {
        # A <-> B mutual cycle, no code exit → deadlocked
        "a": {"doc": "docs/A.md", "verdict": "BLOCKED", "blocked_on": ["docs/B.md"]},
        "b": {"doc": "docs/B.md", "verdict": "BLOCKED", "blocked_on": ["docs/A.md"]},
        # C clean (code), D blocked on C → D drains, not deadlocked
        "c": {"doc": "docs/C.md", "verdict": "SUPPORTED"},
        "d": {"doc": "docs/D.md", "verdict": "BLOCKED", "blocked_on": ["docs/C.md"]},
    }
    dead, _states = vd._deadlocked_docs(cache)
    assert dead == ["docs/A.md", "docs/B.md"]


def test_weak_components_groups_cycle() -> None:
    states = {
        "docs/A.md": {"blocked_on": {"docs/B.md"}},
        "docs/B.md": {"blocked_on": {"docs/A.md"}},
        "docs/Z.md": {"blocked_on": set()},
    }
    comps = vd._weak_components({"docs/A.md", "docs/B.md", "docs/Z.md"}, states)
    comp_sets = sorted([sorted(c) for c in comps])
    assert ["docs/A.md", "docs/B.md"] in comp_sets
    assert ["docs/Z.md"] in comp_sets


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
        "b2": {"doc": "docs/B.md", "verdict": "BLOCKED", "blocked_on": ["docs/C.md"]},
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

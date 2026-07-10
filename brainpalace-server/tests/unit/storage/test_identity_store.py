"""IdentityStore (G5 Task 4): person/alias/link storage + deterministic
candidate lookup. Every test is hermetic against a temp SQLite file."""

from brainpalace_server.storage.identity_store import (
    Alias,
    IdentityStore,
    Link,
    Person,
)


def _store(tmp_path) -> IdentityStore:
    return IdentityStore(tmp_path / "identity.db")


def _person(store, **kw) -> str:
    base = {"kind": "person", "domain": "home"}
    base.update(kw)
    return store.upsert_person(Person(**base))


def test_unnamed_person_is_legal_and_name_person_promotes_in_place(tmp_path):
    store = _store(tmp_path)
    pid = _person(store)  # name defaults to None — the "unknown person" (D3)
    assert store.get_person(pid).name is None
    assert store.count() == 1

    assert store.name_person(pid, "Ivan") is True
    promoted = store.get_person(pid)
    assert promoted.id == pid  # same id, promoted in place
    assert promoted.name == "Ivan"
    assert store.count() == 1  # no new row minted


def test_alias_scoping_two_speakers_two_persons(tmp_path):
    store = _store(tmp_path)
    speaker_a = _person(store, name="Speaker A")
    speaker_b = _person(store, name="Speaker B")
    mama_of_a = _person(store, name="Ana")
    mama_of_b = _person(store, name="Bara")

    store.upsert_alias(Alias(surface="Mama", scope=speaker_a, person_id=mama_of_a))
    store.upsert_alias(Alias(surface="Mama", scope=speaker_b, person_id=mama_of_b))

    from_a = store.resolve_candidates(
        "Mama", scope=speaker_a, at="2026-01-01T00:00:00Z"
    )
    from_b = store.resolve_candidates(
        "Mama", scope=speaker_b, at="2026-01-01T00:00:00Z"
    )

    assert [c["person_id"] for c in from_a] == [mama_of_a]
    assert [c["person_id"] for c in from_b] == [mama_of_b]


def test_time_bounding_resolves_differently_before_and_after_valid_to(tmp_path):
    store = _store(tmp_path)
    dr_old = _person(store, name="Dr Old")
    dr_new = _person(store, name="Dr New")

    # "my doctor" was dr_old until 2025, dr_new from 2025 on.
    store.upsert_alias(
        Alias(surface="my doctor", person_id=dr_old, valid_to="2025-01-01T00:00:00Z")
    )
    store.upsert_alias(
        Alias(surface="my doctor", person_id=dr_new, valid_from="2025-01-01T00:00:00Z")
    )

    before = store.resolve_candidates("my doctor", at="2024-06-01T00:00:00Z")
    after = store.resolve_candidates("my doctor", at="2026-06-01T00:00:00Z")

    assert [c["person_id"] for c in before] == [dr_old]
    assert [c["person_id"] for c in after] == [dr_new]


def test_unresolved_link_round_trips_with_candidate_set(tmp_path):
    store = _store(tmp_path)
    p1 = _person(store, name="Maybe One")
    p2 = _person(store, name="Maybe Two")
    cands = [
        {"person_id": p1, "score": 4.0, "evidence": ["alias:scope"]},
        {"person_id": p2, "score": 3.0, "evidence": ["alias:global"]},
    ]
    lid = store.add_link(
        Link(
            ref="scan-1#0",
            ref_kind="span",
            role="mentioned",
            method="alias_match",
            at="2026-02-02T00:00:00Z",
            person_id=None,  # unresolved is a legal terminal state (D7)
            candidates=cands,
            span_start=3,
            span_end=7,
        )
    )
    unresolved = store.unresolved()
    assert len(unresolved) == 1
    link = unresolved[0]
    assert link.id == lid
    assert link.person_id is None
    assert link.candidates == cands  # JSON round-trips intact
    assert link.span_start == 3 and link.span_end == 7


def test_retract_link_leaves_person_and_alias_intact(tmp_path):
    store = _store(tmp_path)
    pid = _person(store, name="Ivan")
    store.upsert_alias(Alias(surface="Ivo", person_id=pid))
    lid = store.add_link(
        Link(
            ref="scan-2#0",
            ref_kind="chunk",
            role="speaker",
            method="user_asserted",
            at="2026-03-03T00:00:00Z",
            person_id=pid,
        )
    )
    assert store.links_for_person(pid) != []

    assert store.retract_link(lid) is True
    assert store.links_for_person(pid) == []  # link gone
    assert store.get_person(pid).name == "Ivan"  # person intact
    # alias intact — it still resolves the surface
    assert [c["person_id"] for c in store.resolve_candidates("Ivo")] == [pid]


def test_resolve_candidates_returns_ranked_list_and_never_auto_selects_on_tie(tmp_path):
    store = _store(tmp_path)
    a = _person(store, name="Ann A")
    b = _person(store, name="Ann B")
    # Same surface + same (global) scope bound to two different persons: a tie.
    store.upsert_alias(Alias(surface="Ann", person_id=a))
    store.upsert_alias(Alias(surface="Ann", person_id=b))

    cands = store.resolve_candidates("Ann", at="2026-04-04T00:00:00Z")
    assert len(cands) == 2  # both returned, none auto-selected
    assert cands[0]["score"] == cands[1]["score"]  # a genuine tie
    assert {c["person_id"] for c in cands} == {a, b}


def test_scoped_alias_outranks_global_for_same_surface(tmp_path):
    store = _store(tmp_path)
    speaker = _person(store, name="Speaker")
    scoped = _person(store, name="Scoped Mama")
    global_p = _person(store, name="Global Mama")
    store.upsert_alias(Alias(surface="Mama", scope=speaker, person_id=scoped))
    store.upsert_alias(Alias(surface="Mama", person_id=global_p))

    cands = store.resolve_candidates("Mama", scope=speaker, at="2026-05-05T00:00:00Z")
    assert cands[0]["person_id"] == scoped
    assert cands[0]["score"] > cands[1]["score"]
    assert cands[1]["person_id"] == global_p


def test_backfill_rescore_unresolved_link_against_new_alias(tmp_path):
    store = _store(tmp_path)
    pid = _person(store, name="Later Named")
    # Unresolved mention that remembers its surface/scope for re-scoring.
    lid = store.add_link(
        Link(
            ref="scan-9#0",
            ref_kind="span",
            role="mentioned",
            method="alias_match",
            at="2026-06-06T00:00:00Z",
            person_id=None,
            candidates=[],
            surface="Deda",
        )
    )
    assert store.unresolved()[0].candidates == []

    store.upsert_alias(Alias(surface="Deda", person_id=pid))
    assert store.backfill() == 1

    refreshed = store.unresolved()[0]
    assert refreshed.id == lid
    assert refreshed.person_id is None  # never auto-resolved
    assert [c["person_id"] for c in refreshed.candidates] == [pid]


def test_stale_mark_marks_mentions_but_not_speaker_links(tmp_path):
    store = _store(tmp_path)
    pid = _person(store, name="P")
    speaker = store.add_link(
        Link(
            ref="scan-7#0",
            ref_kind="chunk",
            role="speaker",
            method="user_asserted",
            at="2026-07-07T00:00:00Z",
            person_id=pid,
        )
    )
    mention = store.add_link(
        Link(
            ref="scan-7#1",
            ref_kind="span",
            role="mentioned",
            method="alias_match",
            at="2026-07-07T00:00:00Z",
            person_id=pid,
        )
    )
    assert store.stale_mark("scan-7") == 1  # only the mention

    links = {link.id: link.stale for link in store.links_for_person(pid)}
    assert links[speaker] == 0  # speaker link untouched
    assert links[mention] == 1


def test_delete_by_source_drops_links_but_keeps_persons(tmp_path):
    store = _store(tmp_path)
    pid = _person(store, name="P")
    store.add_link(
        Link(
            ref="scan-5",  # participant refs the bare source_id
            ref_kind="session",
            role="participant",
            method="call_log",
            at="2026-08-08T00:00:00Z",
            person_id=pid,
        )
    )
    store.add_link(
        Link(
            ref="scan-5#2",
            ref_kind="chunk",
            role="speaker",
            method="user_asserted",
            at="2026-08-08T00:00:00Z",
            person_id=pid,
        )
    )
    assert store.delete_by_source("scan-5") == 2
    assert store.links_for_person(pid) == []
    assert store.get_person(pid).name == "P"  # person survives
    assert store.count() == 1


def test_source_addressing_is_not_a_like_pattern(tmp_path):
    # `_` and `%` are SQL LIKE wildcards, and real source_ids contain
    # underscores (`msg_2026_07_09`). A LIKE-based prefix match would delete a
    # DIFFERENT source's links — silent data loss. The prefix compare must be
    # exact. Regression: `ref LIKE 'a_b#%'` also matches 'axb#0'.
    store = _store(tmp_path)
    pid = _person(store, name="P")
    for ref in ("a_b#0", "axb#0"):
        store.add_link(
            Link(
                ref=ref,
                ref_kind="chunk",
                role="speaker",
                method="user_asserted",
                at="2026-08-08T00:00:00Z",
                person_id=pid,
            )
        )
    assert store.delete_by_source("a_b") == 1
    surviving = [link.ref for link in store.links_for_person(pid)]
    assert surviving == ["axb#0"]


def test_stale_mark_is_not_a_like_pattern(tmp_path):
    store = _store(tmp_path)
    pid = _person(store, name="P")
    for ref in ("a_b#0", "axb#0"):
        store.add_link(
            Link(
                ref=ref,
                ref_kind="chunk",
                role="mentioned",
                method="llm_inferred",
                at="2026-08-08T00:00:00Z",
                person_id=pid,
            )
        )
    assert store.stale_mark("a_b") == 1


def test_external_ref_link_round_trips(tmp_path):
    store = _store(tmp_path)
    pid = _person(store, name="Voice Person")
    store.add_link(
        Link(
            ref="voice-cluster-3",  # opaque external key (D5)
            ref_kind="external",
            role="participant",
            method="llm_inferred",
            at="2026-09-09T00:00:00Z",
            person_id=pid,
            confidence=0.6,
        )
    )
    links = store.links_for_person(pid)
    assert len(links) == 1
    assert links[0].ref == "voice-cluster-3"
    assert links[0].ref_kind == "external"
    assert links[0].confidence == 0.6
    # An external ref is not addressed by any source_id, so delete_by_source
    # for an unrelated source leaves it alone.
    assert store.delete_by_source("voice-cluster-3") == 0


def test_sensitivity_defaults_to_normal_and_is_stored(tmp_path):
    store = _store(tmp_path)
    normal = _person(store, name="Neighbour")
    third_party = _person(store, name="Third Party", sensitivity="private")
    assert store.get_person(normal).sensitivity == "normal"
    assert store.get_person(third_party).sensitivity == "private"

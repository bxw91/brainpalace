"""Phase 4 Task 3 — deterministic NL -> timeline plan compiler."""

from brainpalace_server.services.timeline_compiler import TimelinePlan, compile_timeline


def test_history_of() -> None:
    assert compile_timeline("history of auth.py") == TimelinePlan(entity="auth.py")


def test_timeline_of_strips_article() -> None:
    assert compile_timeline("timeline of the retry policy") == TimelinePlan(
        entity="retry policy"
    )


def test_evolution_of() -> None:
    assert compile_timeline("evolution of the cache design") == TimelinePlan(
        entity="cache design"
    )


def test_how_did_x_evolve() -> None:
    assert compile_timeline("how did the auth decision evolve") == TimelinePlan(
        entity="auth decision"
    )


def test_how_has_x_changed_over_time() -> None:
    # "over time" is after the verb → entity is clean without a trailing strip
    assert compile_timeline("how has config.py changed over time") == TimelinePlan(
        entity="config.py"
    )


def test_used_to() -> None:
    assert compile_timeline("config.py used to import requests") == TimelinePlan(
        entity="config.py"
    )


def test_trailing_over_time_stripped() -> None:
    assert compile_timeline("history of auth.py over time") == TimelinePlan(
        entity="auth.py"
    )


def test_plain_retrieval_returns_none() -> None:
    # no evolution verb after the entity -> not a timeline question
    assert compile_timeline("how did I configure authentication") is None


def test_relationship_phrasing_returns_none() -> None:
    # graph phrasing, no temporal marker
    assert compile_timeline("what depends on auth.py") is None


def test_compute_phrasing_returns_none() -> None:
    assert compile_timeline("how many decisions did I make") is None


def test_empty_entity_returns_none() -> None:
    assert compile_timeline("history of the") is None


def test_pronoun_entity_returns_none() -> None:
    # H1: "used to" with a pronoun subject must NOT compile — otherwise the
    # executor resolves "i"/"it" via unbounded substring to an arbitrary busy
    # node and the auto-router returns that wrong non-empty timeline over hybrid.
    assert compile_timeline("i used to use redis") is None
    assert compile_timeline("it used to work that way") is None

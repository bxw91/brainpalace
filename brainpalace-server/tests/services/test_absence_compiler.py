"""Phase 3 Task 3 — deterministic NL -> absence plan compiler."""

from brainpalace_server.services.absence_compiler import AbsencePlan, compile_absence

METRICS = ["distance", "duration", "weight", "note"]
SOURCES = ["session", "gmail", "chat"]
DOMAINS = ["chat-life", "mail"]


def test_metric_but_not() -> None:
    p = compile_absence(
        "subjects with distance but not duration", METRICS, SOURCES, DOMAINS
    )
    assert p == AbsencePlan(
        partition="metric", present_in="distance", absent_from="duration"
    )


def test_source_partition_precedence() -> None:
    p = compile_absence(
        "what did I discuss in gmail but not in session", METRICS, SOURCES, DOMAINS
    )
    assert p is not None
    assert (p.partition, p.present_in, p.absent_from) == ("source", "gmail", "session")


def test_metric_restriction_on_source() -> None:
    p = compile_absence(
        "duration recorded in gmail but not session", METRICS, SOURCES, DOMAINS
    )
    assert p is not None
    assert p.partition == "source" and p.metric == "duration"


def test_without_split() -> None:
    p = compile_absence("weight in chat without gmail", METRICS, SOURCES, DOMAINS)
    assert p is not None
    assert (p.partition, p.present_in, p.absent_from) == ("source", "chat", "gmail")


def test_month_year_range() -> None:
    p = compile_absence(
        "distance but not duration in January 2026", METRICS, SOURCES, DOMAINS
    )
    assert p is not None
    assert p.since == "2026-01-01T00:00:00"
    assert p.until == "2026-02-01T00:00:00"


def test_freetext_returns_none() -> None:
    # neither "planned" nor "implemented" is a stored value -> no plan
    assert (
        compile_absence("planned but never implemented", METRICS, SOURCES, DOMAINS)
        is None
    )


def test_no_split_returns_none() -> None:
    assert (
        compile_absence("how many distance records", METRICS, SOURCES, DOMAINS) is None
    )


def test_cross_column_returns_none() -> None:
    # left resolves only as metric, right only as source -> not same column
    assert compile_absence("distance but not gmail", METRICS, SOURCES, DOMAINS) is None


def test_substring_not_matched() -> None:
    # word-boundary only: "weight" must NOT resolve from "weightlifting"
    assert compile_absence("weightlifting but not running", ["weight"], [], []) is None

"""Phase 2 Task 3 — deterministic NL -> scan plan compiler."""

from brainpalace_server.services.scan_compiler import ScanPlan, compile_scan


def test_quoted_term_wins() -> None:
    p = compile_scan('which week did I mention "entity resolution" most')
    assert p is not None
    assert p.term == "entity resolution"
    assert p.group_by == "week"
    assert p.order == "desc"
    assert p.limit == 1


def test_bare_term_after_mention() -> None:
    p = compile_scan("which week did I mention foobar the most")
    assert p == ScanPlan(term="foobar", group_by="week", order="desc", limit=1)


def test_say_the_word() -> None:
    p = compile_scan("how many times did I say the word refactor")
    assert p is not None and p.term == "refactor" and p.group_by is None


def test_least_orders_ascending() -> None:
    p = compile_scan("which week did I mention foobar the least")
    assert p is not None and p.order == "asc" and p.limit == 1


def test_per_month_grouping() -> None:
    p = compile_scan("how often did I talk about caching per month")
    assert p is not None and p.term == "caching" and p.group_by == "month"


def test_month_year_range() -> None:
    p = compile_scan('how many times did I mention "graph" in January 2026')
    assert p is not None
    assert p.since == "2026-01-01T00:00:00"
    assert p.until == "2026-02-01T00:00:00"


def test_stopword_term_never_compiles() -> None:
    # 'mentioned in the docs' — captured word is a stopword, not a term.
    assert compile_scan("which files were mentioned in the docs") is None


def test_no_term_returns_none() -> None:
    assert compile_scan("what is the architecture of the indexer") is None


def test_explicit_single_token_becomes_term() -> None:
    # Explicit `--mode scan`: a bare one-word query is the term, no quotes needed.
    p = compile_scan("profile", explicit=True)
    assert p is not None and p.term == "profile" and p.group_by is None
    # Same as if it had been quoted.
    assert compile_scan('"profile"', explicit=True) == p


def test_bare_single_token_is_strict_without_explicit() -> None:
    # The auto-router (explicit=False, the default) never guesses a term.
    assert compile_scan("profile") is None


def test_explicit_multiword_stays_strict() -> None:
    # Two words, no quotes/tell: which one to count is ambiguous -> None.
    assert compile_scan("user profile", explicit=True) is None


def test_explicit_too_short_stays_strict() -> None:
    assert compile_scan("x", explicit=True) is None

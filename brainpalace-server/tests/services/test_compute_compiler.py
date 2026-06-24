from brainpalace_server.models.query import QueryMode
from brainpalace_server.services.compute_compiler import compile_compute

M = ["sales", "files_touched"]


def test_mode_enum_has_compute():
    assert QueryMode.COMPUTE.value == "compute"


def test_highest_week_is_sum_desc_limit1():
    p = compile_compute("which week had the highest sales", M)
    assert (p.op, p.group_by, p.order, p.limit, p.metric) == (
        "sum",
        "week",
        "desc",
        1,
        "sales",
    )


def test_lowest_week_is_sum_asc_limit1():
    p = compile_compute("which week had the lowest sales", M)
    assert (p.op, p.order, p.limit) == ("sum", "asc", 1)


def test_total_sum_ungrouped():
    p = compile_compute("what is the total sales", M)
    assert (p.op, p.group_by, p.metric) == ("sum", None, "sales")


def test_count_per_month():
    p = compile_compute("how many files_touched per month", M)
    assert (p.op, p.group_by) == ("count", "month")


def test_paraphrase_resolves_via_token_overlap():
    # user says "files", metric is "files_touched"
    p = compile_compute("how many files did I touch", ["files_touched"], ["session"])
    assert p is not None and p.metric == "files_touched"


def test_month_year_sets_range():
    p = compile_compute("total sales in march 2026", M)
    assert p.since == "2026-03-01T00:00:00" and p.until == "2026-04-01T00:00:00"


def test_bare_month_no_range():
    p = compile_compute("total sales in march", M)
    assert p.since is None and p.until is None


def test_no_metric_returns_none_for_fallback():
    assert compile_compute("how is the weather", M) is None
    assert compile_compute("show me the auth code", M) is None

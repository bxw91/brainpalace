"""Unit tests for the generic cross-surface parity harness."""

import pytest

from brainpalace_cli.doc_sync import contract_parity as cp


@pytest.fixture(autouse=True)
def _isolate():
    cp.clear_contracts()
    yield
    cp.clear_contracts()


def test_all_surfaces_equal_sot_passes():
    cp.register_contract(
        "c",
        sot=lambda: {"a", "b"},
        surfaces={"x": lambda: {"a", "b"}, "y": lambda: {"b", "a"}},
    )
    assert cp.check_all() == []


def test_surface_missing_a_token_fails_that_surface():
    cp.register_contract("c", sot=lambda: {"a", "b"}, surfaces={"x": lambda: {"a"}})
    (m,) = cp.check_all()
    assert m.surface == "x"
    assert m.missing == frozenset({"b"})
    assert m.extra == frozenset()


def test_surface_with_extra_token_fails_that_surface():
    cp.register_contract("c", sot=lambda: {"a"}, surfaces={"x": lambda: {"a", "z"}})
    (m,) = cp.check_all()
    assert m.surface == "x"
    assert m.extra == frozenset({"z"})


def test_extractor_raises_reports_surface_not_crash():
    def boom():
        raise RuntimeError("nope")

    cp.register_contract("c", sot=lambda: {"a"}, surfaces={"x": boom})
    (m,) = cp.check_all()
    assert m.surface == "x"
    assert m.error is not None and "nope" in m.error


def test_sot_raises_reports_sot():
    def boom():
        raise RuntimeError("sot-broke")

    cp.register_contract("c", sot=boom, surfaces={"x": lambda: {"a"}})
    (m,) = cp.check_all()
    assert m.surface == "<sot>"
    assert m.error is not None and "sot-broke" in m.error


def test_format_mismatches_names_surface_and_tokens():
    cp.register_contract("c", sot=lambda: {"a", "b"}, surfaces={"x": lambda: {"a"}})
    out = cp.format_mismatches(cp.check_all())
    assert "c" in out and "x" in out and "b" in out

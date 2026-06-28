"""Tests for int/float keep-unset behavior in ask_field."""

from brainpalace_cli import prompt_render as pr
from brainpalace_cli.config_fields import FieldSpec


def test_int_field_none_default_keeps_unset(monkeypatch):
    monkeypatch.setattr("click.prompt", lambda *a, **k: "")  # empty answer
    spec = FieldSpec("git_indexing.depth", "git_indexing", 0, "Depth", "", "int")
    assert pr.ask_field(spec, default=None) is None


def test_int_field_returns_int_not_string(monkeypatch):
    monkeypatch.setattr(
        "click.prompt", lambda *a, **k: 42
    )  # Click coerces with type=int
    spec = FieldSpec("git_indexing.depth", "git_indexing", 0, "Depth", "", "int")
    assert pr.ask_field(spec, default=10) == 42 and isinstance(
        pr.ask_field(spec, default=10), int
    )

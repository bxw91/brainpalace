from brainpalace_cli import prompt_render as pr
from brainpalace_cli.config_fields import FieldSpec


def test_numbered_choice_accepts_number(monkeypatch):
    monkeypatch.setattr("click.prompt", lambda *a, **k: "2")
    assert pr.numbered_choice("p", ["openai", "cohere", "ollama"], "openai") == "cohere"


def test_numbered_choice_accepts_value(monkeypatch):
    monkeypatch.setattr("click.prompt", lambda *a, **k: "ollama")
    assert pr.numbered_choice("p", ["openai", "cohere", "ollama"], "openai") == "ollama"


def test_ask_field_bool(monkeypatch):
    monkeypatch.setattr("click.confirm", lambda *a, **k: True)
    spec = FieldSpec(
        "reranker.enabled",
        "reranker",
        0,
        "Enable reranking?",
        "second-stage re-scoring",
        "bool",
    )
    assert pr.ask_field(spec, default=False) is True

from brainpalace_cli import config_fields as cf
from brainpalace_cli import config_review as cr


def test_resolve_value_prefers_project_then_global_then_default(tmp_path):
    merged = {"embedding": {"provider": "cohere"}}
    val, src = cf.resolve_value("embedding.provider", merged)
    assert (val, src) == ("cohere", "global")  # present in merged (global<project)
    val, src = cf.resolve_value("reranker.enabled", {})
    assert (val, src) == (False, "default")  # falls back to model default


# Forgiving mock: scripted answers, then "c" (Continue) once exhausted so the
# menu always terminates. The control prompt accepts number / A / C / E only.
def test_continue_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr("click.prompt", lambda *a, **k: "c")  # C = continue
    assert cr.review_config(tmp_path, on_consent=lambda spec: None) == {}


def test_exit_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr("click.prompt", lambda *a, **k: "e")  # E = exit/cancel
    assert cr.review_config(tmp_path, on_consent=lambda spec: None) is None


def test_drill_into_division_edits_only_that_group(monkeypatch, tmp_path):
    answers = iter(["1", "ollama"])  # division 1 (embedding), set provider, then C
    monkeypatch.setattr("click.prompt", lambda *a, **k: next(answers, "c"))
    edits = cr.review_config(tmp_path, on_consent=lambda spec: None)
    assert edits and all(dp.startswith("embedding.") for dp in edits)


def test_consent_fields_route_to_callback(monkeypatch, tmp_path):
    seen = []
    answers = iter(["a"])  # edit-all, then C once exhausted
    monkeypatch.setattr("click.prompt", lambda *a, **k: next(answers, "c"))
    monkeypatch.setattr("click.confirm", lambda *a, **k: False)
    cr.review_config(tmp_path, on_consent=lambda spec: seen.append(spec.dotpath))
    assert "session_indexing.enabled" in seen  # consent field never plain-prompted

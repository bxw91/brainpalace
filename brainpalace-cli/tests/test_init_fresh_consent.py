from pathlib import Path

from brainpalace_cli import config_fields as cf
from brainpalace_cli.commands.init import _fresh_on_consent


def _cb(edits, merged, **kw):
    return _fresh_on_consent(
        edits, merged, project_root=Path("."), plugin_present=True, **kw
    )


def test_embed_sessions_records_and_shows_provider_tag(monkeypatch, capsys):
    monkeypatch.setattr(
        "brainpalace_cli.commands.init._preview_embedding",
        lambda root: ("openai", "text-embedding-3-large"),
    )
    monkeypatch.setattr("click.confirm", lambda *a, **k: True)
    edits = {}
    _cb(edits, {"session_indexing": {"enabled": False}})(
        cf.FIELD_SPECS["session_indexing.enabled"]
    )
    assert edits["session_indexing.enabled"] is True
    assert "openai" in capsys.readouterr().out.lower()


def test_git_enabled_also_prompts_depth(monkeypatch):
    answers = iter([True])  # confirm git on
    monkeypatch.setattr("click.confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr("click.prompt", lambda *a, **k: 5000)  # depth
    edits = {}
    _cb(edits, {"git_indexing": {"enabled": False}})(
        cf.FIELD_SPECS["git_indexing.enabled"]
    )
    assert edits["git_indexing.enabled"] is True
    assert edits["git_indexing.depth"] == 5000


def test_git_disabled_does_not_prompt_depth(monkeypatch):
    monkeypatch.setattr("click.confirm", lambda *a, **k: False)
    edits = {}
    _cb(edits, {"git_indexing": {"enabled": True}})(
        cf.FIELD_SPECS["git_indexing.enabled"]
    )
    assert edits["git_indexing.enabled"] is False
    assert "git_indexing.depth" not in edits


def test_redrill_reprompts_with_prior_edit_as_default(monkeypatch):
    # Re-drilling re-prompts the consent field (no sticky seen-guard), seeding the
    # default from the prior grid edit (shared edits map).
    defaults: list = []
    answers = iter([True, False])

    def fake_confirm(label, default=False):
        defaults.append(default)
        return next(answers)

    monkeypatch.setattr("click.confirm", fake_confirm)
    monkeypatch.setattr("click.prompt", lambda *a, **k: 0)
    edits: dict = {}
    cb = _cb(edits, {"git_indexing": {"enabled": False}})
    spec = cf.FIELD_SPECS["git_indexing.enabled"]
    cb(spec)  # merged default False -> True
    cb(spec)  # re-prompt; default reflects the prior edit (True)
    assert len(defaults) == 2
    assert defaults == [False, True]
    assert edits["git_indexing.enabled"] is False

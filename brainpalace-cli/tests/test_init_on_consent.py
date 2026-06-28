"""Tests for _interactive_on_consent: warned, None-safe, dedup'd."""

from brainpalace_cli import config_fields as cf
from brainpalace_cli.commands.init import _interactive_on_consent


def test_consent_bool_records_edit_and_warns(monkeypatch, capsys):
    monkeypatch.setattr("click.confirm", lambda *a, **k: True)
    edits = {}
    _interactive_on_consent(edits, {"git_indexing": {"enabled": False}})(
        cf.FIELD_SPECS["git_indexing.enabled"]
    )
    assert edits["git_indexing.enabled"] is True
    assert "secret" in capsys.readouterr().out.lower()


def test_consent_choice_none_current_does_not_write_none_string(monkeypatch):
    # current is None → must NOT default to the literal "None" (finding #4).
    # Uses extraction.mode (the shared consent field) since session_extraction.mode
    # has been removed.
    monkeypatch.setattr(
        "brainpalace_cli.prompt_render.numbered_choice",
        lambda label, opts, default: default,  # user keeps default
    )
    edits = {}
    _interactive_on_consent(edits, {})(cf.FIELD_SPECS["extraction.mode"])
    assert edits.get("extraction.mode") != "None"


def test_provider_mode_warns_about_env(monkeypatch, capsys):
    monkeypatch.setattr(
        "brainpalace_cli.prompt_render.numbered_choice", lambda *a, **k: "provider"
    )
    edits = {}
    _interactive_on_consent(edits, {"extraction": {"mode": "off"}})(
        cf.FIELD_SPECS["extraction.mode"]
    )
    assert "EXTRACTION_PROVIDER_ENABLED" in capsys.readouterr().out


def test_redrill_reprompts_consent_with_prior_edit_as_default(monkeypatch):
    # Re-drilling a division MUST re-prompt its consent field (so a value can be
    # changed), seeding the default from the prior grid edit (shared edits map).
    defaults: list = []
    answers = iter([True, False])

    def fake_confirm(label, default=False):
        defaults.append(default)
        return next(answers)

    monkeypatch.setattr("click.confirm", fake_confirm)
    edits: dict = {}
    cb = _interactive_on_consent(edits, {"git_indexing": {"enabled": False}})
    spec = cf.FIELD_SPECS["git_indexing.enabled"]
    cb(spec)  # first drill: merged default False -> user sets True
    cb(spec)  # re-drill: re-prompts, default now reflects the prior edit (True)
    assert len(defaults) == 2  # re-prompted (no sticky seen-guard)
    assert defaults == [False, True]  # second default = prior edit
    assert edits["git_indexing.enabled"] is False  # last answer wins

"""Interactive index-target picker (_prompt_index_target): folder + type asked
BEFORE the config grid, populating the existing folders / include_code locals."""

from __future__ import annotations

from unittest.mock import patch

from brainpalace_cli.commands.init import _prompt_index_target


def test_root_default_keeps_folders_empty_and_type_both(tmp_path):
    """Enter (`.`) keeps root → folders empty; 'both' → include_code True."""
    prompts = iter([".", "both"])
    with patch(
        "brainpalace_cli.commands.init.click.prompt",
        side_effect=lambda *a, **k: next(prompts),
    ):
        folders, include_code = _prompt_index_target(
            tmp_path, (), True, folders_explicit=False, code_explicit=False
        )
    assert folders == ()  # root default → unchanged, downstream falls back to root
    assert include_code is True


def test_subfolder_and_docs_only(tmp_path):
    sub = tmp_path / "src"
    sub.mkdir()
    prompts = iter(["src", "docs"])
    with patch(
        "brainpalace_cli.commands.init.click.prompt",
        side_effect=lambda *a, **k: next(prompts),
    ):
        folders, include_code = _prompt_index_target(
            tmp_path, (), True, folders_explicit=False, code_explicit=False
        )
    assert folders == (str(sub.resolve()),)
    assert include_code is False


def test_bad_path_reprompts_until_valid(tmp_path):
    good = tmp_path / "docs"
    good.mkdir()
    prompts = iter(["nope", "docs", "both"])
    with patch(
        "brainpalace_cli.commands.init.click.prompt",
        side_effect=lambda *a, **k: next(prompts),
    ):
        folders, include_code = _prompt_index_target(
            tmp_path, (), True, folders_explicit=False, code_explicit=False
        )
    assert folders == (str(good.resolve()),)
    assert include_code is True


def test_folders_explicit_skips_folder_prompt(tmp_path):
    """-F given → folder prompt suppressed; only the type prompt runs."""
    prompts = iter(["docs"])  # single answer → type prompt only
    with patch(
        "brainpalace_cli.commands.init.click.prompt",
        side_effect=lambda *a, **k: next(prompts),
    ):
        folders, include_code = _prompt_index_target(
            tmp_path,
            ("/preset",),
            True,
            folders_explicit=True,
            code_explicit=False,
        )
    assert folders == ("/preset",)  # untouched
    assert include_code is False


def test_code_explicit_skips_type_prompt(tmp_path):
    """--no-code given → type prompt suppressed; include_code kept as passed."""
    prompts = iter(["."])  # single answer → folder prompt only
    with patch(
        "brainpalace_cli.commands.init.click.prompt",
        side_effect=lambda *a, **k: next(prompts),
    ):
        folders, include_code = _prompt_index_target(
            tmp_path, (), False, folders_explicit=False, code_explicit=True
        )
    assert folders == ()
    assert include_code is False  # untouched by any type prompt

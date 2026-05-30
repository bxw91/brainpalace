"""Tests for ensure_gitignore_entry (B5)."""

from __future__ import annotations

from pathlib import Path

from brainpalace_cli.commands.init import ensure_gitignore_entry


def test_creates_gitignore_when_absent(tmp_path: Path) -> None:
    """No .gitignore → the file is created containing the entry."""
    added = ensure_gitignore_entry(tmp_path)
    assert added is True
    assert (tmp_path / ".gitignore").read_text() == ".brainpalace/\n"


def test_appends_to_existing(tmp_path: Path) -> None:
    """Existing .gitignore without the entry → entry appended on a new line."""
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n*.log\n")
    added = ensure_gitignore_entry(tmp_path)
    assert added is True
    assert gi.read_text().splitlines() == [
        "node_modules/",
        "*.log",
        ".brainpalace/",
    ]


def test_noop_when_entry_present(tmp_path: Path) -> None:
    """Existing .gitignore already containing .brainpalace/ → no change."""
    gi = tmp_path / ".gitignore"
    gi.write_text(".brainpalace/\nfoo\n")
    added = ensure_gitignore_entry(tmp_path)
    assert added is False
    assert gi.read_text() == ".brainpalace/\nfoo\n"


def test_noop_when_entry_present_without_slash(tmp_path: Path) -> None:
    """A `.brainpalace` line (no trailing slash) counts as already present."""
    gi = tmp_path / ".gitignore"
    gi.write_text(".brainpalace\n")
    added = ensure_gitignore_entry(tmp_path)
    assert added is False
    assert gi.read_text() == ".brainpalace\n"


def test_adds_separator_when_no_trailing_newline(tmp_path: Path) -> None:
    """Existing .gitignore without a trailing newline → separator inserted."""
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/")  # no trailing newline
    added = ensure_gitignore_entry(tmp_path)
    assert added is True
    assert gi.read_text() == "node_modules/\n.brainpalace/\n"

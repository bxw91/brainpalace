"""Inherited-override gate (D4) unit tests + reranker re-ask integration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

import brainpalace_cli.commands.init as initmod
from brainpalace_cli.commands.init_plan import inherited_change_gate


def test_gate_keeps_inherited_when_declined():
    with patch("click.confirm", return_value=False):
        value, changed = inherited_change_gate(
            "Reranker", "reranker.enabled", {"reranker": {"enabled": True}}
        )
    assert changed is False
    assert value is True  # surfaces inherited value; caller writes nothing


def test_gate_collects_bool_override_when_accepted():
    with (
        patch("click.confirm", side_effect=[True]),
        patch("click.prompt", return_value="false"),
    ):
        value, changed = inherited_change_gate(
            "Reranker", "reranker.enabled", {"reranker": {"enabled": True}}
        )
    assert changed is True
    assert value is False


# ---------------------------------------------------------------------------
# Integration tests — init sparse/override invariant for reranker
#
# The conftest autouse fixture `_isolate_global_config` points XDG_CONFIG_HOME
# at an empty temp dir, so by default there is NO global config. The sparse
# invariant for the reranker gate applies when a global config EXISTS (the
# project inherits from global and should not duplicate that value). Tests that
# verify sparseness create a minimal global config first.
# ---------------------------------------------------------------------------


def _read(state_dir: Path) -> dict:
    p = state_dir / "config.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _write_global(monkeypatch, content: str) -> None:
    """Write ``content`` to the XDG global config.yaml that tests see.

    The conftest isolation fixture already set XDG_CONFIG_HOME to an empty
    temp dir; just create the brainpalace subdir and write the file there.
    """
    xdg = Path(os.environ["XDG_CONFIG_HOME"])
    bp_dir = xdg / "brainpalace"
    bp_dir.mkdir(parents=True, exist_ok=True)
    (bp_dir / "config.yaml").write_text(content)


def _invoke(tmp_path: Path, monkeypatch, args, input_str: str):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(initmod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(initmod, "claude_plugin_installed", lambda **k: False)
    return CliRunner().invoke(initmod.init_command, args, input=input_str)


def test_init_sparse_when_reranker_inherited(tmp_path, monkeypatch):
    """With a global config, declining the gate writes no reranker override."""
    # Establish a global config that has reranker.enabled=true.  The project
    # inherits it; a declined gate must write nothing for reranker (sparse).
    _write_global(
        monkeypatch,
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "reranker:\n  enabled: true\n",
    )
    args = [
        "--path",
        str(tmp_path),
        "--no-start",
        "--no-extract",
        "--no-sessions",
        "--no-archive",
        "--no-git-history",
        "--no-graphrag-extract",
    ]
    # Prompt order (all per-feature prompts suppressed by flags except reranker
    # gate): reranker-change? n, lemma? n, compute? y, Proceed y
    r = _invoke(tmp_path, monkeypatch, args, input_str="n\nn\ny\ny\n")
    assert r.exit_code == 0, r.output
    cfg = _read(tmp_path / ".brainpalace")
    assert "reranker" not in (cfg or {}), (
        "Declining the gate must not write a project reranker override "
        "(sparse-config invariant)."
    )


def test_init_writes_reranker_override_when_changed(tmp_path, monkeypatch):
    """Accept the reranker gate and change to false -> written to project config."""
    _write_global(
        monkeypatch,
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "reranker:\n  enabled: true\n",
    )
    args = [
        "--path",
        str(tmp_path),
        "--no-start",
        "--no-extract",
        "--no-sessions",
        "--no-archive",
        "--no-git-history",
        "--no-graphrag-extract",
    ]
    # reranker-change? y, enabled? false, lemma? n, compute? y, Proceed y
    r = _invoke(tmp_path, monkeypatch, args, input_str="y\nfalse\nn\ny\ny\n")
    assert r.exit_code == 0, r.output
    cfg = _read(tmp_path / ".brainpalace")
    assert cfg.get("reranker", {}).get("enabled") is False

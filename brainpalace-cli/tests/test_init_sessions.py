"""Phase 4 — `brainpalace init --sessions` conscious session-memory opt-in.

Session indexing is default-off (privacy-first: it ingests chat transcripts).
init surfaces it: --sessions writes session_indexing.enabled: true into the
project config.yaml; the server reads that block at startup. --no-sessions and
the non-interactive default leave the block absent.
"""

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.init import init_command


def _run(args, monkeypatch, tmp_path):
    # Isolate XDG so a real user config.yaml is not copied over the default.
    monkeypatch.setattr(
        "brainpalace_cli.commands.init.get_xdg_config_dir",
        lambda: tmp_path / "xdg",
    )
    return CliRunner().invoke(init_command, args)


def _cfg(tmp_path):
    return yaml.safe_load((tmp_path / ".brainpalace" / "config.yaml").read_text())


def test_init_sessions_flag_enables_block(tmp_path, monkeypatch):
    result = _run(["--path", str(tmp_path), "--sessions"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    cfg = _cfg(tmp_path)
    assert cfg["session_indexing"]["enabled"] is True
    # Must not clobber the provider defaults written alongside it.
    assert cfg["embedding"]["provider"] == "openai"


def test_init_no_sessions_leaves_block_absent(tmp_path, monkeypatch):
    result = _run(["--path", str(tmp_path), "--no-sessions"], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert "session_indexing" not in _cfg(tmp_path)


def test_init_default_non_interactive_leaves_block_absent(tmp_path, monkeypatch):
    # CliRunner has no TTY -> privacy-first default is off, no block written.
    result = _run(["--path", str(tmp_path)], monkeypatch, tmp_path)
    assert result.exit_code == 0, result.output
    assert "session_indexing" not in _cfg(tmp_path)

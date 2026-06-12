"""`brainpalace read-only on|off|status` writes/reads server.read_only."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands.read_only import read_only_command


def _project(tmp_path: Path) -> Path:
    bp = tmp_path / ".brainpalace"
    bp.mkdir()
    (bp / "config.yaml").write_text(yaml.safe_dump({"server": {}}))
    return tmp_path


def _clean_env(monkeypatch):
    for v in (
        "BRAINPALACE_CONFIG",
        "BRAINPALACE_STATE_DIR",
        "DOC_SERVE_STATE_DIR",
        "BRAINPALACE_READ_ONLY",
    ):
        monkeypatch.delenv(v, raising=False)


def test_on_sets_flag(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    proj = _project(tmp_path)
    monkeypatch.chdir(proj)
    result = CliRunner().invoke(read_only_command, ["on"])
    assert result.exit_code == 0, result.output
    cfg = yaml.safe_load((proj / ".brainpalace" / "config.yaml").read_text())
    assert cfg["server"]["read_only"] is True


def test_off_unsets_flag(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    proj = _project(tmp_path)
    (proj / ".brainpalace" / "config.yaml").write_text(
        yaml.safe_dump({"server": {"read_only": True}})
    )
    monkeypatch.chdir(proj)
    result = CliRunner().invoke(read_only_command, ["off"])
    assert result.exit_code == 0, result.output
    cfg = yaml.safe_load((proj / ".brainpalace" / "config.yaml").read_text())
    assert "read_only" not in cfg.get("server", {})


def test_status_reports(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    proj = _project(tmp_path)
    (proj / ".brainpalace" / "config.yaml").write_text(
        yaml.safe_dump({"server": {"read_only": True}})
    )
    monkeypatch.chdir(proj)
    result = CliRunner().invoke(read_only_command, ["status"])
    assert result.exit_code == 0, result.output
    assert "ON" in result.output.upper()

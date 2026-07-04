"""Smoke tests for plugin helper scripts — output must be machine-parseable."""

import json
import subprocess
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[3] / "brainpalace-plugin"
if not PLUGIN_DIR.is_dir():
    pytest.skip("brainpalace-plugin not present", allow_module_level=True)


def test_bp_setup_check_emits_valid_json(tmp_path):
    script = PLUGIN_DIR / "scripts" / "bp-setup-check.sh"
    res = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    data = json.loads(res.stdout)  # must parse regardless of environment
    assert isinstance(data["brainpalace_installed"], bool)
    assert isinstance(data["large_dirs"], list)
    assert isinstance(data["api_keys"], dict)


def test_bp_setup_check_survives_quote_in_version(tmp_path):
    """A quote/backslash in any interpolated value must not break the JSON."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "brainpalace"
    fake.write_text("#!/bin/sh\necho 'evil \"version\\\\' \n", encoding="utf-8")
    fake.chmod(0o755)
    import os

    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")
    script = PLUGIN_DIR / "scripts" / "bp-setup-check.sh"
    res = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    data = json.loads(res.stdout)
    assert 'evil "version' in data["brainpalace_version"]

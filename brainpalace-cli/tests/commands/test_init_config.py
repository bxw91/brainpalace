from pathlib import Path

import yaml

from brainpalace_cli.commands.init import (
    build_default_provider_config,
    migrate_graph_store_to_sqlite,
    read_graphrag_store_type,
    write_default_provider_config,
    write_git_config,
)


def test_default_graphrag_store_is_sqlite():
    cfg = build_default_provider_config()
    assert cfg["graphrag"]["enabled"] is True
    assert cfg["graphrag"]["store_type"] == "sqlite"


def test_write_git_config_merges(tmp_path: Path):
    sd = tmp_path / ".brainpalace"
    write_default_provider_config(sd)
    write_git_config(sd, enabled=True)
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is True
    assert "embedding" in data  # provider block preserved


def test_write_git_config_none_is_noop(tmp_path: Path):
    sd = tmp_path / ".brainpalace"
    write_default_provider_config(sd)
    write_git_config(sd, enabled=None)
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert "git_indexing" not in data


def test_write_git_config_disabled_writes_false(tmp_path: Path):
    sd = tmp_path / ".brainpalace"
    write_default_provider_config(sd)
    write_git_config(sd, enabled=False)
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["git_indexing"]["enabled"] is False


def _write_simple_store(sd: Path) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "config.yaml").write_text(
        "embedding:\n  provider: openai\n  model: text-embedding-3-large\n"
        "graphrag:\n  enabled: true\n  store_type: simple\n  use_code_metadata: true\n"
    )


def test_migrate_graph_store_flips_simple_and_preserves(tmp_path: Path):
    sd = tmp_path / ".brainpalace"
    _write_simple_store(sd)
    assert migrate_graph_store_to_sqlite(sd) is True
    data = yaml.safe_load((sd / "config.yaml").read_text())
    assert data["graphrag"]["store_type"] == "sqlite"
    assert data["graphrag"]["enabled"] is True  # preserved
    assert data["embedding"]["provider"] == "openai"  # preserved
    # idempotent: already sqlite -> no change
    assert migrate_graph_store_to_sqlite(sd) is False


def test_migrate_graph_store_noop_when_absent(tmp_path: Path):
    sd = tmp_path / ".brainpalace"
    sd.mkdir(parents=True)
    (sd / "config.yaml").write_text("embedding:\n  provider: openai\n")
    assert migrate_graph_store_to_sqlite(sd) is False
    assert read_graphrag_store_type(sd) is None


def test_read_graphrag_store_type(tmp_path: Path):
    sd = tmp_path / ".brainpalace"
    _write_simple_store(sd)
    assert read_graphrag_store_type(sd) == "simple"

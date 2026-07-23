"""Tests for config migration engine and CLI migrate/diff commands."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from brainpalace_cli.cli import cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# Config with old dead keys that should be stripped on migration: langextract
# graphrag keys, the dead top-level `api:` block, and legacy
# `session_extraction.mode`. `git_indexing` is a live bystander section that must
# survive migration untouched.
OLD_SCHEMA_CONFIG: dict = {
    "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
    "summarization": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "graphrag": {
        "enabled": True,
        "store_type": "simple",
        "use_code_metadata": True,
        "use_llm_extraction": True,
        "doc_extractor": "langextract",
    },
    "git_indexing": {"enabled": True, "depth": 5000},
    "api": {"host": "127.0.0.1", "port": 8000},
    "session_extraction": {"mode": "off", "quiescence_seconds": 1800},
}

OLD_SCHEMA_FALSE_CONFIG: dict = {
    "graphrag": {
        "enabled": True,
        "store_type": "simple",
        "use_code_metadata": True,
        "use_llm_extraction": False,
    },
}

# Current schema: no dead keys (no langextract, no api:, no session_extraction.mode).
CURRENT_SCHEMA_CONFIG: dict = {
    "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
    "summarization": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "graphrag": {
        "enabled": True,
        "store_type": "simple",
        "use_code_metadata": True,
    },
    "git_indexing": {"enabled": True, "depth": 5000},
    "session_extraction": {"quiescence_seconds": 1800},
}

EMPTY_CONFIG: dict = {}


# ---------------------------------------------------------------------------
# Unit tests: migrate_config (dict-level)
# ---------------------------------------------------------------------------


class TestMigrateConfigDict:
    """Tests for migrate_config() with dict inputs."""

    def test_migrate_old_schema_strips_langextract_keys(self) -> None:
        """Strip all langextract/doc_extractor dead keys from graphrag section."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config(OLD_SCHEMA_CONFIG)

        assert result.already_current is False
        graphrag = result.migrated.get("graphrag", {})
        assert "use_llm_extraction" not in graphrag
        assert "doc_extractor" not in graphrag
        # M2.1: must NOT map to extraction.mode (no surprise billing)
        assert "extraction" not in result.migrated
        assert len(result.changes) >= 1

    def test_migrate_use_llm_extraction_false_stripped(self) -> None:
        """use_llm_extraction=False is stripped (no doc_extractor added)."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config(OLD_SCHEMA_FALSE_CONFIG)

        assert result.already_current is False
        graphrag = result.migrated.get("graphrag", {})
        assert "use_llm_extraction" not in graphrag
        assert "doc_extractor" not in graphrag
        assert len(result.changes) >= 1

    def test_migrate_already_current_config(self) -> None:
        """migrate_config on a current-schema dict returns already_current=True."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config(CURRENT_SCHEMA_CONFIG)

        assert result.already_current is True
        assert result.changes == []

    def test_migrate_empty_config(self) -> None:
        """migrate_config on empty dict returns already_current=True with no changes."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config(EMPTY_CONFIG)

        assert result.already_current is True
        assert result.changes == []

    def test_migrate_preserves_other_keys(self) -> None:
        """migrate_config leaves live sections (embedding, summarization,
        git_indexing) untouched while dropping the dead ones."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config(OLD_SCHEMA_CONFIG)

        # These sections must be preserved exactly
        assert result.migrated["embedding"] == OLD_SCHEMA_CONFIG["embedding"]
        assert result.migrated["summarization"] == OLD_SCHEMA_CONFIG["summarization"]
        assert result.migrated["git_indexing"] == OLD_SCHEMA_CONFIG["git_indexing"]
        # ...and the dead top-level api: block is gone
        assert "api" not in result.migrated

    def test_migrate_does_not_mutate_input(self) -> None:
        """migrate_config must not mutate the original input dict."""
        import copy

        from brainpalace_cli.config_migrate import migrate_config

        original = copy.deepcopy(OLD_SCHEMA_CONFIG)
        migrate_config(OLD_SCHEMA_CONFIG)

        # Input should not have been modified
        assert OLD_SCHEMA_CONFIG == original


# ---------------------------------------------------------------------------
# Unit tests: diff_config (dict-level)
# ---------------------------------------------------------------------------


class TestDiffConfigDict:
    """Tests for diff_config() with dict inputs."""

    def test_diff_shows_removed_langextract_keys(self) -> None:
        """diff_config shows removed langextract/doc_extractor dead keys."""
        from brainpalace_cli.config_migrate import diff_config

        result = diff_config(OLD_SCHEMA_CONFIG)

        assert isinstance(result, str)
        assert len(result) > 0
        # The diff should show the removed keys
        assert "use_llm_extraction" in result or "doc_extractor" in result

    def test_diff_no_changes_returns_empty(self) -> None:
        """diff_config returns empty string for already-current config."""
        from brainpalace_cli.config_migrate import diff_config

        result = diff_config(CURRENT_SCHEMA_CONFIG)

        assert result == ""


# ---------------------------------------------------------------------------
# File-based tests
# ---------------------------------------------------------------------------


class TestMigrateConfigFile:
    """Tests for migrate_config_file() and diff_config_file()."""

    def test_migrate_config_file_writes_migrated_yaml(self, tmp_path: Path) -> None:
        """migrate_config_file writes migrated YAML; strips langextract keys."""
        from brainpalace_cli.config_migrate import migrate_config_file

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(OLD_SCHEMA_CONFIG, default_flow_style=False),
            encoding="utf-8",
        )

        result = migrate_config_file(config_file)

        assert result.already_current is False
        # Re-read the file to verify it was actually written
        updated = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        graphrag = updated.get("graphrag", {})
        assert "use_llm_extraction" not in graphrag
        assert "doc_extractor" not in graphrag

    def test_diff_config_file_shows_diff(self, tmp_path: Path) -> None:
        """diff_config_file returns non-empty diff for old-schema config."""
        from brainpalace_cli.config_migrate import diff_config_file

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(OLD_SCHEMA_CONFIG, default_flow_style=False),
            encoding="utf-8",
        )

        result = diff_config_file(config_file)

        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestMigrateCliCommand:
    """Tests for 'brainpalace config migrate' CLI command."""

    def test_migrate_updates_file(self, tmp_path: Path) -> None:
        """migrate command strips dead langextract keys from old-schema YAML."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(OLD_SCHEMA_CONFIG, default_flow_style=False),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "migrate", "--file", str(config_file)])

        assert result.exit_code == 0
        updated_text = config_file.read_text(encoding="utf-8")
        assert "use_llm_extraction" not in updated_text
        assert "doc_extractor" not in updated_text

    def test_migrate_already_current(self, tmp_path: Path) -> None:
        """migrate command reports 'already up to date' for current-schema config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(CURRENT_SCHEMA_CONFIG, default_flow_style=False),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "migrate", "--file", str(config_file)])

        assert result.exit_code == 0
        assert "already up to date" in result.output.lower()

    def test_migrate_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        """migrate --dry-run shows changes without modifying the file."""
        config_file = tmp_path / "config.yaml"
        original_content = yaml.safe_dump(OLD_SCHEMA_CONFIG, default_flow_style=False)
        config_file.write_text(original_content, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["config", "migrate", "--file", str(config_file), "--dry-run"]
        )

        assert result.exit_code == 0
        # File must remain unchanged
        assert config_file.read_text(encoding="utf-8") == original_content

    def test_migrate_no_config_found(self) -> None:
        """migrate exits 0 with informative message when no config file is found."""
        from unittest.mock import patch

        runner = CliRunner()
        with patch(
            "brainpalace_cli.commands.config._find_config_file", return_value=None
        ):
            result = runner.invoke(cli, ["config", "migrate"])

        assert result.exit_code == 0
        assert "No config file found" in result.output


class TestDiffCliCommand:
    """Tests for 'brainpalace config diff' CLI command."""

    def test_diff_shows_changes(self, tmp_path: Path) -> None:
        """diff command shows changes for old-schema config (dead langextract keys)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(OLD_SCHEMA_CONFIG, default_flow_style=False),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "diff", "--file", str(config_file)])

        assert result.exit_code == 0
        # The diff output should reference the removed dead keys
        assert "use_llm_extraction" in result.output or "doc_extractor" in result.output

    def test_diff_no_changes(self, tmp_path: Path) -> None:
        """diff command reports no changes for current-schema config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.safe_dump(CURRENT_SCHEMA_CONFIG, default_flow_style=False),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "diff", "--file", str(config_file)])

        assert result.exit_code == 0
        assert "up to date" in result.output.lower()

    def test_diff_no_config_found(self) -> None:
        """diff exits 0 with informative message when no config file is found."""
        from unittest.mock import patch

        runner = CliRunner()
        with patch(
            "brainpalace_cli.commands.config._find_config_file", return_value=None
        ):
            result = runner.invoke(cli, ["config", "diff"])

        assert result.exit_code == 0
        assert "No config file found" in result.output


# ---------------------------------------------------------------------------
# R3 guard tests: strip-on-load migration (M2.1)
# ---------------------------------------------------------------------------


class TestStripLangextractKeys:
    """R3 guard: _strip_langextract_keys drops dead keys, no extraction.mode mapping."""

    def test_config_with_doc_extractor_langextract_loads_clean(self) -> None:
        """doc_extractor: langextract loads clean — key stripped, no extraction.mode."""
        from brainpalace_cli.config_migrate import migrate_config

        cfg = {"graphrag": {"enabled": True, "doc_extractor": "langextract"}}
        result = migrate_config(cfg)
        assert result.already_current is False
        assert "doc_extractor" not in result.migrated.get("graphrag", {})
        # M2.1: must NOT map to extraction.mode
        assert "extraction" not in result.migrated
        assert len(result.changes) >= 1

    def test_all_langextract_keys_stripped(self) -> None:
        """All 4 dead keys are stripped: doc_extractor, use_llm_extraction,
        langextract_provider, langextract_model."""
        from brainpalace_cli.config_migrate import migrate_config

        cfg = {
            "graphrag": {
                "enabled": True,
                "use_llm_extraction": True,
                "doc_extractor": "langextract",
                "langextract_provider": "anthropic",
                "langextract_model": "claude-3-haiku",
            }
        }
        result = migrate_config(cfg)
        g = result.migrated.get("graphrag", {})
        assert "doc_extractor" not in g
        assert "use_llm_extraction" not in g
        assert "langextract_provider" not in g
        assert "langextract_model" not in g
        assert "extraction" not in result.migrated  # no surprise billing

    def test_no_langextract_keys_is_already_current(self) -> None:
        """Clean config has no migrations to run."""
        from brainpalace_cli.config_migrate import migrate_config

        cfg = {"graphrag": {"enabled": True}}
        result = migrate_config(cfg)
        assert result.already_current is True


# ---------------------------------------------------------------------------
# Guard tests: dead top-level api: and legacy session_extraction.mode
# ---------------------------------------------------------------------------


class TestDropDeadApiSection:
    """_drop_dead_api_section drops api:, never maps it to bind:."""

    def test_dead_api_section_dropped(self) -> None:
        """Top-level api: is removed (dead duplicate of bind:/config.json)."""
        from brainpalace_cli.config_migrate import migrate_config

        cfg = {
            "api": {"host": "127.0.0.1", "port": 8000},
            "graphrag": {"enabled": True},
        }
        result = migrate_config(cfg)
        assert result.already_current is False
        assert "api" not in result.migrated
        # Must NOT be mapped to a bind: section (no stale host/port override)
        assert "bind" not in result.migrated
        assert len(result.changes) >= 1

    def test_no_api_section_is_already_current(self) -> None:
        """A config without api: needs no api migration."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config({"graphrag": {"enabled": True}})
        assert result.already_current is True


class TestDropLegacySessionExtractionMode:
    """_drop_legacy_session_extraction_mode drops mode, never maps it across."""

    def test_mode_dropped_quiescence_preserved(self) -> None:
        """session_extraction.mode is removed; quiescence_seconds is preserved."""
        from brainpalace_cli.config_migrate import migrate_config

        cfg = {"session_extraction": {"mode": "off", "quiescence_seconds": 1800}}
        result = migrate_config(cfg)
        assert result.already_current is False
        assert result.migrated["session_extraction"] == {"quiescence_seconds": 1800}
        # Must NOT map to extraction.mode (no surprise re-enable of paid engine)
        assert "extraction" not in result.migrated

    def test_section_removed_when_mode_was_sole_key(self) -> None:
        """session_extraction is dropped entirely when mode was its only field."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config({"session_extraction": {"mode": "provider"}})
        assert result.already_current is False
        assert "session_extraction" not in result.migrated
        assert "extraction" not in result.migrated

    def test_mode_absent_is_already_current(self) -> None:
        """session_extraction without mode needs no migration."""
        from brainpalace_cli.config_migrate import migrate_config

        result = migrate_config({"session_extraction": {"quiescence_seconds": 1800}})
        assert result.already_current is True

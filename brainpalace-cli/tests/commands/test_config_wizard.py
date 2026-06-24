"""Integration tests for brainpalace config wizard command."""

from pathlib import Path
from unittest.mock import patch

import yaml
from click.testing import CliRunner

from brainpalace_cli.commands import config as config_command_module
from brainpalace_cli.commands.config import config_group


class TestConfigWizard:
    """Tests for config wizard sub-command."""

    def test_wizard_shows_ollama_prompts(self, tmp_path: Path) -> None:
        """Wizard shows batch_size and request_delay_ms when provider is ollama."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                config_group,
                ["wizard"],
                input=(
                    "ollama\n"
                    "nomic-embed-text\n"
                    "20\n"
                    "100\n"
                    "anthropic\n"
                    "claude-haiku-4-5-20251001\n"
                    "1\n"
                    "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                    "n\nn\nn\ny\nn\n"
                    "1\n"
                    "\n"
                ),
            )
            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "Batch size" in result.output
            assert "Request delay" in result.output

            config_file = Path(".brainpalace") / "config.yaml"
            assert config_file.exists()
            config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            assert config["embedding"]["params"]["batch_size"] == 20
            assert config["embedding"]["params"]["request_delay_ms"] == 100

    def test_wizard_skips_prompts_for_openai_and_cohere(self, tmp_path: Path) -> None:
        """Wizard does not show batch_size/request_delay_ms for openai or cohere."""
        runner = CliRunner()
        for provider in ["openai", "cohere"]:
            with runner.isolated_filesystem(temp_dir=tmp_path):
                result = runner.invoke(
                    config_group,
                    ["wizard"],
                    input=(
                        f"{provider}\n"
                        "some-model\n"
                        "anthropic\n"
                        "claude-haiku-4-5-20251001\n"
                        "1\n"
                        "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                        "n\nn\nn\ny\nn\n"
                        "1\n"
                        "\n"
                    ),
                )
                assert result.exit_code == 0, f"{provider}: {result.output}"
                assert "Unknown top-level key" not in result.output
                assert "Batch size" not in result.output
                assert "Request delay" not in result.output

    def test_wizard_rejects_invalid_batch_size(self, tmp_path: Path) -> None:
        """Wizard rejects batch_size values not in [1, 5, 10, 20, 50, 100]."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                config_group,
                ["wizard"],
                input=(
                    "ollama\n"
                    "nomic-embed-text\n"
                    "7\n"
                    "10\n"
                    "0\n"
                    "anthropic\n"
                    "claude-haiku-4-5-20251001\n"
                    "1\n"
                    "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                    "n\nn\nn\ny\nn\n"
                    "1\n"
                    "\n"
                ),
            )
            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "is not one of" in result.output.lower()

    def test_wizard_global_asks_and_writes_dashboard_settings(
        self, tmp_path: Path
    ) -> None:
        """--global prompts for dashboard autostart + port and writes the
        `dashboard:` block to the global config.yaml."""
        runner = CliRunner()
        xdg = tmp_path / "xdg"
        with runner.isolated_filesystem(temp_dir=tmp_path):
            with patch.object(
                config_command_module, "get_xdg_config_dir", return_value=xdg
            ):
                result = runner.invoke(
                    config_group,
                    ["wizard", "--global"],
                    input=(
                        "openai\n"
                        "text-embedding-3-small\n"
                        "anthropic\n"
                        "claude-haiku-4-5-20251001\n"
                        "1\n"  # graphrag mode
                        "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                        "n\nn\nn\nn\nn\n"  # sessions, archive, git, rerank, lemma
                        "1\n"  # deployment: localhost
                        "\n"  # api port: default
                        "n\n"  # dashboard autostart? -> no
                        "9999\n"  # dashboard port
                    ),
                )
            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "Auto-start the web dashboard" in result.output
            cfg = yaml.safe_load((xdg / "config.yaml").read_text(encoding="utf-8"))
            assert cfg["dashboard"] == {"autostart": False, "port": 9999}

    def test_wizard_non_global_omits_dashboard_block(self, tmp_path: Path) -> None:
        """A per-project (non-global) wizard run does not ask for or write
        dashboard settings (those are global control-plane settings)."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                config_group,
                ["wizard"],
                input=(
                    "openai\n"
                    "text-embedding-3-small\n"
                    "anthropic\n"
                    "claude-haiku-4-5-20251001\n"
                    "1\n"
                    "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                    "n\nn\nn\nn\nn\n"
                    "1\n"
                    "\n"
                ),
            )
            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "Auto-start the web dashboard" not in result.output
            cfg = yaml.safe_load(
                (Path(".brainpalace") / "config.yaml").read_text(encoding="utf-8")
            )
            assert "dashboard" not in cfg

    def test_wizard_rejects_negative_request_delay(self, tmp_path: Path) -> None:
        """Wizard rejects negative request_delay_ms values."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                config_group,
                ["wizard"],
                input=(
                    "ollama\n"
                    "nomic-embed-text\n"
                    "10\n"
                    "-1\n"
                    "0\n"
                    "anthropic\n"
                    "claude-haiku-4-5-20251001\n"
                    "1\n"
                    "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                    "n\nn\nn\ny\nn\n"
                    "1\n"
                    "\n"
                ),
            )
            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "x>=0" in result.output

            config_file = Path(".brainpalace") / "config.yaml"
            assert config_file.exists()
            config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            assert config["embedding"]["params"]["request_delay_ms"] >= 0

    def test_wizard_persists_graphrag_mixed_extraction_mode(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Wizard persists AST+LangExtract mode for mixed repositories."""
        runner = CliRunner()
        monkeypatch.setattr(
            config_command_module,
            "_find_available_api_port",
            lambda *args, **kwargs: 8123,
            raising=False,
        )

        with runner.isolated_filesystem(temp_dir=tmp_path):
            with patch("brainpalace_cli.optional_deps.ensure_extra"):
                result = runner.invoke(
                    config_group,
                    ["wizard"],
                    input=(
                        "openai\n"
                        "text-embedding-3-large\n"
                        "anthropic\n"
                        "claude-haiku-4-5-20251001\n"
                        "2\n"
                        "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                        "n\nn\nn\ny\nn\n"
                        "2\n"
                        "1\n"
                        "\n"
                    ),
                )

            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "On, code + docs" in result.output

            config_file = Path(".brainpalace") / "config.yaml"
            config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            assert config["graphrag"]["enabled"] is True
            assert config["graphrag"]["store_type"] == "sqlite"
            assert config["graphrag"]["use_code_metadata"] is True
            assert config["graphrag"]["doc_extractor"] == "langextract"

    def test_wizard_suggests_and_persists_available_api_port(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Wizard discovers an available API port and writes it to config."""
        runner = CliRunner()
        monkeypatch.setattr(
            config_command_module,
            "_find_available_api_port",
            lambda *args, **kwargs: 8123,
            raising=False,
        )

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                config_group,
                ["wizard"],
                input=(
                    "openai\n"
                    "text-embedding-3-large\n"
                    "anthropic\n"
                    "claude-haiku-4-5-20251001\n"
                    "1\n"
                    "y\ny\n0.7\n"  # compute, rec_extract, min_conf
                    "n\nn\nn\ny\nn\n"
                    "1\n"
                    "\n"
                ),
            )

            assert result.exit_code == 0, result.output
            assert "Unknown top-level key" not in result.output
            assert "available API port" in result.output
            assert "8000-8300" in result.output

            config_file = Path(".brainpalace") / "config.yaml"
            config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            assert config["api"]["host"] == "127.0.0.1"
            assert config["api"]["port"] == 8123

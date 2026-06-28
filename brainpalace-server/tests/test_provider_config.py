"""Tests for GraphRAGConfig model and ProviderSettings.graphrag field (Phase G).

Covers the three required behaviours:
  1. Full graphrag: YAML section parses into a GraphRAGConfig with correct values.
  2. No graphrag: section → default GraphRAGConfig with all fields None.
  3. Partial graphrag: section (only enabled: true) → set field non-None, rest None.

An additional end-to-end test exercises load_provider_settings() directly.
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from brainpalace_server.config.provider_config import (
    GraphRAGConfig,
    ProviderSettings,
    clear_settings_cache,
    load_provider_settings,
)


class TestGraphRAGConfigDefaults:
    """Case 2 — no graphrag: section means all fields are None."""

    def test_provider_settings_default_graphrag_all_none(self) -> None:
        """ProviderSettings() yields a GraphRAGConfig with every field None."""
        settings = ProviderSettings()
        grc = settings.graphrag
        assert isinstance(grc, GraphRAGConfig)
        assert grc.enabled is None
        assert grc.store_type is None
        assert grc.index_path is None
        assert grc.extraction_model is None
        assert grc.max_triplets_per_chunk is None
        assert grc.use_code_metadata is None
        assert grc.traversal_depth is None
        assert grc.rrf_k is None

    def test_graphrag_config_standalone_defaults(self) -> None:
        """GraphRAGConfig() itself has all fields None."""
        grc = GraphRAGConfig()
        for field_name in GraphRAGConfig.model_fields:
            assert (
                getattr(grc, field_name) is None
            ), f"Expected {field_name!r} to be None by default"

    def test_provider_settings_without_graphrag_key(self) -> None:
        """A raw dict with no graphrag key produces a default GraphRAGConfig."""
        raw: dict = {
            "embedding": {"provider": "openai", "model": "text-embedding-3-large"},
        }
        settings = ProviderSettings(**raw)
        assert settings.graphrag.enabled is None


class TestGraphRAGConfigFullSection:
    """Case 1 — full graphrag: section is parsed with correct values."""

    def test_full_graphrag_section_parsed(self) -> None:
        """GraphRAGConfig fields populated from dict; langextract fields removed."""
        raw = {
            "graphrag": {
                "enabled": True,
                "store_type": "kuzu",
                "index_path": "/tmp/graph",
                "extraction_model": "gpt-4o",
                "max_triplets_per_chunk": 10,
                "use_code_metadata": False,
                "traversal_depth": 3,
                "rrf_k": 60,
            }
        }
        settings = ProviderSettings(**raw)
        grc = settings.graphrag

        assert grc.enabled is True
        assert grc.store_type == "kuzu"
        assert grc.index_path == "/tmp/graph"
        assert grc.extraction_model == "gpt-4o"
        assert grc.max_triplets_per_chunk == 10
        assert grc.use_code_metadata is False
        assert grc.traversal_depth == 3
        assert grc.rrf_k == 60

    def test_graphrag_config_direct_construction(self) -> None:
        """GraphRAGConfig can be constructed directly with all fields."""
        grc = GraphRAGConfig(
            enabled=True,
            store_type="simple",
            index_path="/data/graph",
            rrf_k=50,
        )
        assert grc.enabled is True
        assert grc.store_type == "simple"
        assert grc.index_path == "/data/graph"
        assert grc.rrf_k == 50
        # unset fields remain None
        assert grc.extraction_model is None
        assert grc.traversal_depth is None


class TestGraphRAGConfigPartialSection:
    """Case 3 — partial graphrag: section: set field is non-None, rest None."""

    def test_only_enabled_set(self) -> None:
        """Only enabled: true — all other fields stay None."""
        raw = {"graphrag": {"enabled": True}}
        settings = ProviderSettings(**raw)
        grc = settings.graphrag

        assert grc.enabled is True
        assert grc.store_type is None
        assert grc.index_path is None
        assert grc.extraction_model is None
        assert grc.max_triplets_per_chunk is None
        assert grc.use_code_metadata is None
        assert grc.traversal_depth is None
        assert grc.rrf_k is None

    def test_only_store_type_and_index_path_set(self) -> None:
        """Only store_type and index_path set — all other fields stay None."""
        raw = {"graphrag": {"store_type": "kuzu", "index_path": "/var/graph"}}
        settings = ProviderSettings(**raw)
        grc = settings.graphrag

        assert grc.store_type == "kuzu"
        assert grc.index_path == "/var/graph"
        assert grc.enabled is None
        assert grc.rrf_k is None

    @pytest.mark.parametrize(
        "field,value",
        [
            ("enabled", False),
            ("store_type", "simple"),
            ("max_triplets_per_chunk", 5),
            ("traversal_depth", 2),
            ("rrf_k", 42),
        ],
    )
    def test_single_field_set_rest_none(self, field: str, value: object) -> None:
        """Each individual field can be set alone; all others remain None."""
        raw = {"graphrag": {field: value}}
        settings = ProviderSettings(**raw)
        grc = settings.graphrag

        assert getattr(grc, field) == value
        for other_field in GraphRAGConfig.model_fields:
            if other_field != field:
                assert (
                    getattr(grc, other_field) is None
                ), f"Expected {other_field!r} to be None when only {field!r} is set"


class TestLoadProviderSettingsGraphRAG:
    """End-to-end: load_provider_settings() parses a graphrag: section."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_load_provider_settings_parses_graphrag(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """load_provider_settings() parses graphrag: and logs an info message."""
        fake_path = Path("/fake/.brainpalace/config.yaml")
        with (
            # Patch the live project-file resolver used by
            # load_merged_config_dict (not the legacy _find_config_file, which
            # load_provider_settings no longer calls). This makes proj_file
            # truthy so the patched _load_yaml_config is actually invoked,
            # independent of whether a real config.yaml exists on disk.
            patch(
                "brainpalace_server.config.provider_config._find_project_config_file",
                return_value=fake_path,
            ),
            patch(
                "brainpalace_server.config.provider_config._find_global_config_file",
                return_value=None,
            ),
            patch(
                "brainpalace_server.config.provider_config._load_yaml_config",
                return_value={
                    "graphrag": {
                        "enabled": True,
                        "store_type": "simple",
                        "traversal_depth": 2,
                    }
                },
            ),
            caplog.at_level(logging.INFO),
        ):
            settings = load_provider_settings()

        grc = settings.graphrag
        assert grc.enabled is True
        assert grc.store_type == "simple"
        assert grc.traversal_depth == 2
        assert grc.rrf_k is None
        # The info log must mention graphrag and the new doc reference
        assert "graphrag" in caplog.text.lower()
        assert "PROVIDER_CONFIGURATION.md" in caplog.text


# ---------------------------------------------------------------------------
# Guard tests: langextract fields must NOT exist after R1 removal
# ---------------------------------------------------------------------------


class TestLangextractFieldsRemoved:
    """R1 guard: the 4 inert langextract/doc_extractor fields must be absent."""

    def test_graphrag_config_has_no_use_llm_extraction(self) -> None:
        assert "use_llm_extraction" not in GraphRAGConfig.model_fields

    def test_graphrag_config_has_no_doc_extractor(self) -> None:
        assert "doc_extractor" not in GraphRAGConfig.model_fields

    def test_graphrag_config_has_no_langextract_provider(self) -> None:
        assert "langextract_provider" not in GraphRAGConfig.model_fields

    def test_graphrag_config_has_no_langextract_model(self) -> None:
        assert "langextract_model" not in GraphRAGConfig.model_fields

    def test_settings_has_no_graph_use_llm_extraction(self) -> None:
        from brainpalace_server.config.settings import Settings

        assert (
            not hasattr(
                Settings.model_fields.get("GRAPH_USE_LLM_EXTRACTION", None), "default"
            )
            and "GRAPH_USE_LLM_EXTRACTION" not in Settings.model_fields
        )

    def test_settings_has_no_graph_doc_extractor(self) -> None:
        from brainpalace_server.config.settings import Settings

        assert "GRAPH_DOC_EXTRACTOR" not in Settings.model_fields

    def test_settings_has_no_graph_langextract_provider(self) -> None:
        from brainpalace_server.config.settings import Settings

        assert "GRAPH_LANGEXTRACT_PROVIDER" not in Settings.model_fields

    def test_settings_has_no_graph_langextract_model(self) -> None:
        from brainpalace_server.config.settings import Settings

        assert "GRAPH_LANGEXTRACT_MODEL" not in Settings.model_fields

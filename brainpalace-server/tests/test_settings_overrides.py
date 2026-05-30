"""Tests for _apply_graphrag_yaml_overrides (Phase G — env-wins override).

Each test snapshots the settings attributes it touches, runs the helper,
asserts the expected outcome, then restores both `settings` and `os.environ`
in a finally block so the process-global singleton is never left dirty.
"""

import os

from brainpalace_server.api.main import _apply_graphrag_yaml_overrides
from brainpalace_server.config import settings
from brainpalace_server.config.provider_config import GraphRAGConfig, ProviderSettings


class TestYAMLFillsUnsetSettings:
    """YAML value is applied when the env var is NOT set."""

    def test_yaml_enabled_fills_enable_graph_index(self) -> None:
        """enabled=True in YAML sets settings.ENABLE_GRAPH_INDEX when env unset."""
        env_name = "ENABLE_GRAPH_INDEX"
        prior = settings.ENABLE_GRAPH_INDEX
        # Make sure the env var is not set for this test
        was_set = env_name in os.environ
        saved_env = os.environ.pop(env_name, None)
        try:
            ps = ProviderSettings(graphrag=GraphRAGConfig(enabled=True))
            _apply_graphrag_yaml_overrides(ps)
            assert settings.ENABLE_GRAPH_INDEX is True
        finally:
            settings.ENABLE_GRAPH_INDEX = prior  # type: ignore[assignment]
            if was_set and saved_env is not None:
                os.environ[env_name] = saved_env


class TestEnvWinsOverYAML:
    """Env var presence blocks YAML from overwriting the setting."""

    def test_env_var_blocks_yaml_override(self) -> None:
        """When ENABLE_GRAPH_INDEX env var is set, YAML enabled=True is NOT applied."""
        env_name = "ENABLE_GRAPH_INDEX"
        prior = settings.ENABLE_GRAPH_INDEX
        was_set = env_name in os.environ
        saved_env = os.environ.get(env_name)
        # Set the env var to "false" — this means YAML True must NOT be applied.
        os.environ[env_name] = "false"
        try:
            ps = ProviderSettings(graphrag=GraphRAGConfig(enabled=True))
            _apply_graphrag_yaml_overrides(ps)
            # The setting must NOT have been changed to True — it keeps prior value.
            assert (
                settings.ENABLE_GRAPH_INDEX == prior
            ), "YAML value should NOT overwrite settings when env var is set"
        finally:
            settings.ENABLE_GRAPH_INDEX = prior  # type: ignore[assignment]
            if was_set and saved_env is not None:
                os.environ[env_name] = saved_env
            else:
                os.environ.pop(env_name, None)


class TestNoneYAMLValuesAreSkipped:
    """All-None GraphRAGConfig leaves settings unchanged."""

    def test_none_yaml_values_not_applied(self) -> None:
        """GraphRAGConfig with all None fields changes nothing on settings."""
        prior_store_type = settings.GRAPH_STORE_TYPE
        prior_traversal = settings.GRAPH_TRAVERSAL_DEPTH
        prior_rrf = settings.GRAPH_RRF_K
        # Clear any env vars that would interfere with our check
        env_names = ["GRAPH_STORE_TYPE", "GRAPH_TRAVERSAL_DEPTH", "GRAPH_RRF_K"]
        saved_envs = {k: os.environ.pop(k, None) for k in env_names}
        try:
            ps = ProviderSettings(graphrag=GraphRAGConfig())  # all None
            _apply_graphrag_yaml_overrides(ps)
            assert settings.GRAPH_STORE_TYPE == prior_store_type
            assert settings.GRAPH_TRAVERSAL_DEPTH == prior_traversal
            assert settings.GRAPH_RRF_K == prior_rrf
        finally:
            settings.GRAPH_STORE_TYPE = prior_store_type  # type: ignore[assignment]
            settings.GRAPH_TRAVERSAL_DEPTH = prior_traversal  # type: ignore[assignment]
            settings.GRAPH_RRF_K = prior_rrf  # type: ignore[assignment]
            for k, v in saved_envs.items():
                if v is not None:
                    os.environ[k] = v


class TestNonEnabledFieldApplies:
    """A non-enabled field (store_type) is correctly applied from YAML."""

    def test_store_type_kuzu_applied(self) -> None:
        """store_type='kuzu' in YAML sets settings.GRAPH_STORE_TYPE when env unset."""
        env_name = "GRAPH_STORE_TYPE"
        prior = settings.GRAPH_STORE_TYPE
        was_set = env_name in os.environ
        saved_env = os.environ.pop(env_name, None)
        try:
            ps = ProviderSettings(graphrag=GraphRAGConfig(store_type="kuzu"))
            _apply_graphrag_yaml_overrides(ps)
            assert settings.GRAPH_STORE_TYPE == "kuzu"
        finally:
            settings.GRAPH_STORE_TYPE = prior  # type: ignore[assignment]
            if was_set and saved_env is not None:
                os.environ[env_name] = saved_env

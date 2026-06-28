import pytest

from brainpalace_cli import config_fields as cf


@pytest.mark.parametrize(
    "dotpath,expected",
    [
        ("compute.min_confidence", 0.7),
        ("graphrag.enabled", True),
        ("graphrag.store_type", "sqlite"),
        ("graphrag.use_code_metadata", True),
    ],
)
def test_settings_fallback_defaults_resolve(dotpath, expected):
    """Fields whose pydantic model default is None (the real default lives in
    settings.py) must resolve to their effective code default — parity with the
    dashboard's DEFAULT_FALLBACKS. Regression: bp init rendered these empty."""
    assert cf.resolve_value_layered(dotpath, {}, {}) == (expected, "default")


def test_project_value_reports_project():
    project = {"embedding": {"provider": "ollama"}}
    global_ = {"embedding": {"provider": "cohere"}}
    assert cf.resolve_value_layered("embedding.provider", project, global_) == (
        "ollama",
        "project",
    )


def test_inherited_from_global_reports_global():
    assert cf.resolve_value_layered(
        "embedding.provider", {}, {"embedding": {"provider": "cohere"}}
    ) == ("cohere", "global")


def test_unset_reports_default_from_model():
    val, src = cf.resolve_value_layered("reranker.enabled", {}, {})
    assert (val, src) == (False, "default")

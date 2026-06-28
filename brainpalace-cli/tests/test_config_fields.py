import brainpalace_cli.config_fields as cf


def test_every_model_field_is_auto_covered():
    """Headline invariant: a field on any section model auto-derives a spec."""
    for section, model in cf.SECTION_MODELS.items():
        for fname in model.model_fields:
            assert f"{section}.{fname}" in cf.FIELD_SPECS, f"{section}.{fname} missing"


def test_nested_archive_subfields_are_covered():
    # The nested SessionArchiveConfig must contribute session_indexing.archive.* specs.
    for fname in cf.NESTED_MODELS["session_indexing.archive"].model_fields:
        assert f"session_indexing.archive.{fname}" in cf.FIELD_SPECS


def test_registry_does_not_import_dashboard():
    import importlib
    import sys

    sys.modules.pop("brainpalace_dashboard", None)
    importlib.reload(cf)
    assert "brainpalace_dashboard" not in sys.modules


def test_group_order_is_the_dashboard_section_order_verbatim():
    # Equality is asserted dashboard-side (Task 2); here just assert shape/labels exist.
    assert [k for k, _ in cf.GROUP_ORDER][:2] == ["embedding", "summarization"]
    assert ("session_extraction", "Chat Session : Summarization") in cf.GROUP_ORDER


def test_help_defaults_to_model_description_when_no_override():
    spec = cf.FIELD_SPECS["usage_metrics.retain_days"]
    model_desc = (
        cf.SECTION_MODELS["usage_metrics"].model_fields["retain_days"].description
    )
    assert spec.help == (model_desc or "")  # this field has no FIELD_OVERRIDES help


def test_known_consent_fields_are_tagged_consent():
    for dp in cf.KNOWN_CONSENT_FIELDS:
        assert cf.FIELD_SPECS[dp].init_role == "consent", dp


def test_secret_fields_are_hidden_from_init():
    for dp, spec in cf.FIELD_SPECS.items():
        if spec.secret:
            assert spec.init_role in (
                "hidden",
                "consent",
            ), f"{dp} secret but promptable"


def test_options_ref_resolves_for_every_choice_field():
    for spec in cf.FIELD_SPECS.values():
        if spec.widget == "choice" and spec.options_ref:
            opts = cf.options_for(spec.options_ref)
            assert opts and all(isinstance(o, str) for o in opts)


def test_embedding_provider_options_match_catalog():
    from brainpalace_cli.providers import PROVIDERS

    assert set(cf.options_for("providers:embedding")) == set(PROVIDERS["embedding"])


def test_storage_backend_options_from_public_valid_set():
    from brainpalace_cli import config_schema as cs

    assert set(cf.options_for("validator:storage.backend")) == cs.VALID_STORAGE_BACKENDS

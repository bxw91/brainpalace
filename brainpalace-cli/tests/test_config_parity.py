from brainpalace_cli import config_fields as cf
from brainpalace_cli import config_parity


def test_every_model_field_has_a_spec():
    for section, model in cf.SECTION_MODELS.items():
        for fname in model.model_fields:
            assert f"{section}.{fname}" in cf.FIELD_SPECS
    for fname in cf.NESTED_MODELS["session_indexing.archive"].model_fields:
        assert f"session_indexing.archive.{fname}" in cf.FIELD_SPECS


def test_every_field_has_a_valid_role():
    for spec in cf.FIELD_SPECS.values():
        assert spec.init_role in ("normal", "advanced", "consent", "hidden")


def test_known_consent_fields_are_consent():
    for dp in cf.KNOWN_CONSENT_FIELDS:
        assert cf.FIELD_SPECS[dp].init_role == "consent", dp


def test_every_choice_resolves():
    for spec in cf.FIELD_SPECS.values():
        if spec.widget == "choice" and spec.options_ref:
            assert cf.options_for(spec.options_ref)


def test_secret_fields_are_not_promptable():
    for dp, spec in cf.FIELD_SPECS.items():
        if spec.secret:
            assert spec.init_role in ("hidden", "consent"), dp


def test_every_field_has_a_valid_scope():
    for spec in cf.FIELD_SPECS.values():
        assert spec.scope in ("global", "project", "both"), spec.dotpath


def test_parity_check_passes():
    assert config_parity.check() == []

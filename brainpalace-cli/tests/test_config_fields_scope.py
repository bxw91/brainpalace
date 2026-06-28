from brainpalace_cli import config_fields as cf


def test_every_spec_has_a_valid_scope():
    for spec in cf.FIELD_SPECS.values():
        assert spec.scope in ("global", "project", "both"), spec.dotpath


def test_default_scope_is_both():
    assert cf.FIELD_SPECS["embedding.provider"].scope == "both"


def test_group_fields_no_layer_returns_all():
    # Default (layer=None) must NOT filter — protects non-CLI callers (finding #4).
    # archive.* now renders in its own `session_archiving` section (dotpaths stay
    # session_indexing.archive.*).
    archive_dir = "session_indexing.archive.dir"
    allf = [s.dotpath for s in cf.group_fields("session_archiving")]
    assert archive_dir in allf


def test_project_only_field_hidden_from_global_layer():
    g = [s.dotpath for s in cf.group_fields("session_archiving", layer="global")]
    assert "session_indexing.archive.dir" not in g
    p = [s.dotpath for s in cf.group_fields("session_archiving", layer="project")]
    assert "session_indexing.archive.dir" in p

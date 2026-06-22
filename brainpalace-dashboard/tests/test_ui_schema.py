from brainpalace_cli import config_schema as cs

from brainpalace_dashboard.ui_schema import DASHBOARD_HIDDEN_FIELDS, build_ui_schema


def test_provider_is_first_in_provider_sections():
    """`provider` leads embedding/summarization; `enabled` leads reranker."""
    ui = build_ui_schema()
    first = {s["key"]: s["fields"][0]["key"] for s in ui["sections"]}
    assert first["embedding"] == "provider"
    assert first["summarization"] == "provider"
    assert first["reranker"] == "enabled"


def test_every_known_field_is_present_or_hidden():
    """Every config_schema field appears in the UISchema or is explicitly hidden."""
    ui = build_ui_schema()
    rendered = set()
    for sec in ui["sections"]:
        for fld in sec["fields"]:
            if fld.get("widget") == "group":
                # Nested group (e.g. storage.postgres): account for its children.
                rendered.add(f"{sec['key']}.{fld['key']}")
                for child in fld.get("fields", []):
                    rendered.add(child["dotpath"])
            else:
                rendered.add(f"{sec['key']}.{fld['key']}")
    # The archive (session_indexing.archive) is surfaced as its OWN top-level
    # "Session Archiving" section rather than a nested group, so the nested-object
    # parent key is covered by that section's presence.
    if any(s["key"] == "session_archiving" for s in ui["sections"]):
        rendered.add("session_indexing.archive")
    expected = set()
    section_fields = {
        "embedding": cs.EMBEDDING_KNOWN_FIELDS,
        "summarization": cs.SUMMARIZATION_KNOWN_FIELDS,
        "reranker": cs.RERANKER_KNOWN_FIELDS,
        "storage": cs.STORAGE_KNOWN_FIELDS,
        "graphrag": cs.GRAPHRAG_KNOWN_FIELDS,
        "api": cs.API_KNOWN_FIELDS,
        "server": cs.SERVER_KNOWN_FIELDS,
        "project": cs.PROJECT_KNOWN_FIELDS,
        "query_log": cs.QUERY_LOG_KNOWN_FIELDS,
        "bm25": cs.BM25_KNOWN_FIELDS,
        "git_indexing": cs.GIT_INDEXING_KNOWN_FIELDS,
        "session_indexing": cs.SESSION_INDEXING_KNOWN_FIELDS,
        "session_extraction": cs.SESSION_EXTRACTION_KNOWN_FIELDS,
    }
    for sec, fields in section_fields.items():
        for fld in fields:
            expected.add(f"{sec}.{fld}")
    missing = expected - rendered - set(DASHBOARD_HIDDEN_FIELDS)
    assert not missing, f"config fields missing from UISchema: {sorted(missing)}"


def test_provider_field_is_enum_with_options():
    ui = build_ui_schema()
    emb = next(s for s in ui["sections"] if s["key"] == "embedding")
    provider = next(f for f in emb["fields"] if f["key"] == "provider")
    assert provider["widget"] == "enum"
    assert set(provider["options"]) == set(cs.VALID_EMBEDDING_PROVIDERS)


def test_graphrag_enabled_is_toggle():
    ui = build_ui_schema()
    g = next(s for s in ui["sections"] if s["key"] == "graphrag")
    enabled = next(f for f in g["fields"] if f["key"] == "enabled")
    assert enabled["widget"] == "toggle"


def test_api_key_is_secret():
    ui = build_ui_schema()
    emb = next(s for s in ui["sections"] if s["key"] == "embedding")
    key = next(f for f in emb["fields"] if f["key"] == "api_key")
    assert key["secret"] is True


def test_params_fields_use_dict_widget():
    """embedding/summarization/reranker `params` render as the dict widget."""
    ui = build_ui_schema()
    for sec_key in ("embedding", "summarization", "reranker"):
        sec = next(s for s in ui["sections"] if s["key"] == sec_key)
        params = next(f for f in sec["fields"] if f["key"] == "params")
        assert params["widget"] == "dict"


def test_path_filter_uses_stringlist_widget():
    ui = build_ui_schema()
    gi = next(s for s in ui["sections"] if s["key"] == "git_indexing")
    pf = next(f for f in gi["fields"] if f["key"] == "path_filter")
    assert pf["widget"] == "stringlist"


def test_session_archiving_is_its_own_section():
    """The archive (raw COPY) renders as its own top-level 'Session Archiving'
    section, NOT a sub-group of Session Vector Indexing. Keys stay under
    session_indexing.archive.*."""
    ui = build_ui_schema()
    arch = next(s for s in ui["sections"] if s["key"] == "session_archiving")
    assert arch["label"] == "Session Archiving"
    child_keys = {c["key"] for c in arch["fields"]}
    assert child_keys == {"enabled", "dir", "retain_days", "reconcile_seconds"}
    enabled = next(c for c in arch["fields"] if c["key"] == "enabled")
    assert enabled["widget"] == "toggle"
    assert enabled["dotpath"] == "session_indexing.archive.enabled"
    retain = next(c for c in arch["fields"] if c["key"] == "retain_days")
    assert retain["widget"] == "int"
    # Vector Indexing no longer carries the archive as a nested group.
    si = next(s for s in ui["sections"] if s["key"] == "session_indexing")
    assert si["label"] == "Session Vector Indexing"
    assert not any(f["key"] == "archive" for f in si["fields"])
    # Summarization renamed too.
    sx = next(s for s in ui["sections"] if s["key"] == "session_extraction")
    assert sx["label"] == "Session Summarization"


def test_unhidden_fields_not_in_hidden_map():
    """The B fields are no longer hidden (so they render)."""
    from brainpalace_dashboard.ui_schema import DASHBOARD_HIDDEN_FIELDS

    for dp in (
        "embedding.params",
        "summarization.params",
        "reranker.params",
        "git_indexing.path_filter",
        "session_indexing.archive",
    ):
        assert dp not in DASHBOARD_HIDDEN_FIELDS


def test_schema_includes_provider_descriptor():
    """build_ui_schema() exposes the canonical provider descriptor for the
    frontend's conditional model/base_url/api_key_env rendering."""
    from brainpalace_cli.providers import PROVIDERS

    ui = build_ui_schema()
    assert "providers" in ui
    providers = ui["providers"]
    assert set(providers) == set(PROVIDERS)
    # Spot-check a kind/provider's shape + recommended-first model.
    openai = providers["embedding"]["openai"]
    assert openai["models"][0] == "text-embedding-3-large"
    assert openai["needs_base_url"] is False
    assert openai["default_api_key_env"] == "OPENAI_API_KEY"
    # Ollama needs a base URL and has no key env.
    ollama = providers["summarization"]["ollama"]
    assert ollama["needs_base_url"] is True
    assert ollama["default_api_key_env"] is None


def test_model_presets_sourced_from_descriptor():
    """embedding/summarization/reranker model presets come from PROVIDERS,
    and the stale ids (#7) are gone."""
    ui = build_ui_schema()

    def _presets(section_key: str) -> set[str]:
        sec = next(s for s in ui["sections"] if s["key"] == section_key)
        model = next(f for f in sec["fields"] if f["key"] == "model")
        return set(model.get("presets", []))

    emb = _presets("embedding")
    assert "text-embedding-3-large" in emb
    summ = _presets("summarization")
    assert "claude-haiku-4-5-20251001" in summ
    assert summ.isdisjoint(
        {"claude-3-5-haiku-latest", "claude-sonnet-4-6", "gpt-4o-mini"}
    )
    rer = _presets("reranker")
    assert "cross-encoder/ms-marco-MiniLM-L-6-v2" in rer


def test_provider_and_key_fields_have_help():
    """provider/model/base_url/api_key/api_key_env carry help text (#3/#4/#8)."""
    ui = build_ui_schema()
    for section_key, fields in (
        ("embedding", ("provider", "model", "base_url", "api_key", "api_key_env")),
        ("summarization", ("provider", "model", "base_url", "api_key", "api_key_env")),
        ("reranker", ("enabled", "provider", "model", "base_url")),
    ):
        sec = next(s for s in ui["sections"] if s["key"] == section_key)
        for fld_key in fields:
            fld = next(f for f in sec["fields"] if f["key"] == fld_key)
            assert fld.get("help"), f"{section_key}.{fld_key} missing help"


def test_query_log_section_renders():
    ui = build_ui_schema()
    ql = next(s for s in ui["sections"] if s["key"] == "query_log")
    enabled = next(f for f in ql["fields"] if f["key"] == "enabled")
    assert enabled["widget"] == "toggle"
    retention = next(f for f in ql["fields"] if f["key"] == "retention_days")
    assert retention["widget"] == "int"
    assert retention["min"] == 0
    assert retention["max"] == 365
    assert retention["help"] == "0 = keep forever"


def test_identity_fields_emitted_readonly():
    """state_dir / project_root are surfaced (not hidden) and marked read-only."""
    ui = build_ui_schema()
    by_path = {f["dotpath"]: f for sec in ui["sections"] for f in sec["fields"]}
    assert by_path["project.state_dir"]["readonly"] is True
    assert by_path["project.project_root"]["readonly"] is True
    # An ordinary editable field carries no readonly flag (or False).
    assert not by_path["graphrag.enabled"].get("readonly", False)

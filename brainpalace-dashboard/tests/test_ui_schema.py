from brainpalace_cli import config_schema as cs

from brainpalace_dashboard.ui_schema import DASHBOARD_HIDDEN_FIELDS, build_ui_schema


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

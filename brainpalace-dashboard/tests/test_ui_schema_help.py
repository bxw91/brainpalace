from brainpalace_dashboard.ui_schema import build_ui_schema


def _field(schema, section_key, dotpath):
    section = next(s for s in schema["sections"] if s["key"] == section_key)

    def walk(fields):
        for f in fields:
            if f["dotpath"] == dotpath:
                return f
            if f.get("widget") == "group":
                hit = walk(f.get("fields", []))
                if hit:
                    return hit
        return None

    return walk(section["fields"])


def test_help_present_for_requested_fields():
    schema = build_ui_schema()
    expected = {
        ("storage", "storage.backend"): ["chroma", "postgres"],
        ("graphrag", "graphrag.enabled"): ["knowledge graph"],
        ("graphrag", "graphrag.store_type"): ["simple", "sqlite", "temporal"],
        ("graphrag", "graphrag.use_code_metadata"): ["metadata"],
        ("git_indexing", "git_indexing.enabled"): ["git"],
        ("git_indexing", "git_indexing.depth"): ["0"],
        ("git_indexing", "git_indexing.max_files"): ["files"],
        # session_extraction.mode is HIDDEN (legacy; extraction.mode is canonical).
        # extraction.mode is checked below.
        ("extraction", "extraction.mode"): ["subagent", "provider", "auto", "off"],
    }
    for (section, dotpath), needles in expected.items():
        field = _field(schema, section, dotpath)
        assert field is not None, f"missing field {dotpath}"
        help_text = (field.get("help") or "").lower()
        assert help_text, f"no help for {dotpath}"
        for needle in needles:
            assert needle.lower() in help_text, f"{dotpath} help missing '{needle}'"


def test_reranker_help_distinguishes_providers():
    schema = build_ui_schema()
    help_text = (_field(schema, "reranker", "reranker.provider")["help"] or "").lower()
    assert "sentence-transformers" in help_text and "ollama" in help_text
    assert "cross-encoder" in help_text and "prompt" in help_text


def test_sections_carry_descriptions():
    schema = build_ui_schema()
    by_key = {s["key"]: s for s in schema["sections"]}
    # Session Extraction vs Indexing must each explain themselves.
    assert "summary" in by_key["session_extraction"]["description"].lower()
    si = by_key["session_indexing"]["description"].lower()
    assert "archive" in si or "embed" in si
    for key in ("storage", "graphrag", "git_indexing"):
        assert by_key[key].get("description"), f"{key} missing description"

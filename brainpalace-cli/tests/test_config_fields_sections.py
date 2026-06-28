from brainpalace_cli import config_fields as cf


def test_group_descriptions_present_for_dashboard_keys():
    # The dashboard's section-description keys must all exist on the CLI source.
    expected_keys = {
        "server",
        "storage",
        "graphrag",
        "git_indexing",
        "session_archiving",
        "session_indexing",
        "session_extraction",
        "compute",
        "extraction",
    }
    assert expected_keys <= set(cf.GROUP_DESCRIPTIONS)


def test_group_descriptions_are_nonempty_strings():
    for key, text in cf.GROUP_DESCRIPTIONS.items():
        assert isinstance(text, str) and text.strip(), key

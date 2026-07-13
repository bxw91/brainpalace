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


def test_group_cost_covers_every_section():
    # Every rendered section (GROUP_ORDER + the session_archiving pseudo-section)
    # must carry a cost class — the header badge is not optional.
    keys = {g for g, _ in cf.GROUP_ORDER} | {"session_archiving"}
    assert keys <= set(cf.GROUP_COST)


def test_group_cost_values_are_valid():
    valid = {cf.COST_FREE, cf.COST_LLM, cf.COST_LLM_SUBAGENT}
    for key, cost in cf.GROUP_COST.items():
        assert cost in valid, f"{key}: {cost!r}"

"""All five code surfaces declare exactly the server enum's mode set."""

from brainpalace_cli.doc_sync import mode_parity


def test_query_modes_parity_holds():
    mismatches = mode_parity.query_modes_mismatches()
    assert mismatches == [], mode_parity_report(mismatches)


def mode_parity_report(mismatches):
    from brainpalace_cli.doc_sync.contract_parity import format_mismatches

    return format_mismatches(mismatches)


def test_all_expected_surfaces_registered():
    assert set(mode_parity.MODE_PARITY_SURFACES) == {
        "cli_choice",
        "mcp_literal",
        "hook_guard",
        "mode_meta",
    }

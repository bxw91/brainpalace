"""brainpalace references — CLI wrapper over the /references endpoints."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.commands.references import references_group


def _invoke(args, *, list_resp=None, search_resp=None, embed_resp=None):
    client = MagicMock()
    client.__enter__ = lambda s: s
    client.__exit__ = lambda s, *a: False
    client.references_list.return_value = list_resp or {
        "references": [
            {
                "id": "abc123",
                "domain": "code",
                "source": "gmail",
                "source_id": "acct-1",
                "pointer": "gmail://msg/1",
                "summary": "an invoice",
                "sensitivity": "normal",
            }
        ]
    }
    client.references_search.return_value = search_resp or {
        "results": [
            {
                "id": "abc123",
                "pointer": "gmail://msg/1",
                "summary": "an invoice",
                "score": 0.97,
            }
        ]
    }
    client.references_embed_missing.return_value = embed_resp or {"embedded": 3}
    with patch(
        "brainpalace_cli.commands.references.DocServeClient", return_value=client
    ):
        result = CliRunner().invoke(references_group, args)
    return result, client


def test_references_list_json():
    result, client = _invoke(["list", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["references"][0]["pointer"] == "gmail://msg/1"


def test_references_list_domain_filter():
    result, client = _invoke(["list", "--domain", "glasses"])
    assert result.exit_code == 0, result.output
    client.references_list.assert_called_once_with("glasses")


def test_references_search_passes_query_and_default_deny():
    result, client = _invoke(["search", "power bill", "--json"])
    assert result.exit_code == 0, result.output
    kwargs = client.references_search.call_args.kwargs
    assert kwargs["query"] == "power bill"
    assert kwargs["include_sensitive"] is False


def test_references_search_include_sensitive_opt_in():
    result, client = _invoke(["search", "note", "--include-sensitive"])
    assert result.exit_code == 0, result.output
    assert client.references_search.call_args.kwargs["include_sensitive"] is True


def test_references_resolve_prints_pointer():
    result, client = _invoke(["resolve", "abc123"])
    assert result.exit_code == 0, result.output
    assert "gmail://msg/1" in result.output


def test_references_resolve_unknown_id_errors():
    result, _ = _invoke(["resolve", "nope"])
    assert result.exit_code != 0


def test_references_embed_missing():
    result, client = _invoke(["embed-missing", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["embedded"] == 3
    client.references_embed_missing.assert_called_once_with()

"""Plan E — `brainpalace graph` CLI group."""

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from brainpalace_cli.cli import cli


def _client(**returns):
    c = MagicMock()
    c.__enter__ = MagicMock(return_value=c)
    c.__exit__ = MagicMock(return_value=False)
    for name, value in returns.items():
        getattr(c, name).return_value = value
    return c


def test_graph_path_json():
    payload = {
        "src": "a",
        "dst": "b",
        "paths": [{"node_ids": ["a", "b"], "edges": [], "length": 1}],
        "nodes": [],
    }
    client = _client(graph_path=payload)
    with patch("brainpalace_cli.commands.graph.DocServeClient", return_value=client):
        r = CliRunner().invoke(cli, ["graph", "path", "a", "b", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == payload
    client.graph_path.assert_called_once_with(
        "a", "b", max_depth=6, limit=5, domains=None
    )


def test_graph_impact_human_output_lists_dependents():
    payload = {
        "node": "lib.py:helper",
        "nodes": [
            {
                "id": "api.py:handler",
                "name": "handler",
                "label": "Function",
                "domain": "code",
                "depth": 1,
                "via_predicate": "calls",
                "via_node_id": "lib.py:helper",
            }
        ],
    }
    client = _client(graph_impact=payload)
    with patch("brainpalace_cli.commands.graph.DocServeClient", return_value=client):
        r = CliRunner().invoke(cli, ["graph", "impact", "lib.py:helper"])
    assert r.exit_code == 0, r.output
    assert "handler" in r.output and "calls" in r.output


def test_graph_cochange_passes_options():
    payload = {"node": "/p/a.py", "files": []}
    client = _client(graph_cochange=payload)
    with patch("brainpalace_cli.commands.graph.DocServeClient", return_value=client):
        r = CliRunner().invoke(
            cli, ["graph", "cochange", "/p/a.py", "--min-shared", "3", "--json"]
        )
    assert r.exit_code == 0, r.output
    client.graph_cochange.assert_called_once_with("/p/a.py", min_shared=3, limit=20)


def test_server_error_json_contract():
    from brainpalace_cli.client import ServerError

    client = _client()
    client.graph_impact.side_effect = ServerError(
        "boom", status_code=400, detail="ambiguous"
    )
    with patch("brainpalace_cli.commands.graph.DocServeClient", return_value=client):
        r = CliRunner().invoke(cli, ["graph", "impact", "a.py", "--json"])
    assert r.exit_code != 0
    assert "error" in json.loads(r.output)

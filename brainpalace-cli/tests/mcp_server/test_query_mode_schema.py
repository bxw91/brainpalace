"""The MCP QueryMode Literal equals the server enum, keeps an inline JSON schema
(no $defs), and accepts every mode (the validation that used to reject timeline)."""

from typing import get_args

import pytest
from brainpalace_server.models.query import QueryMode as ServerQueryMode

from brainpalace_cli.mcp_server import schemas
from brainpalace_cli.mcp_server.schemas import QueryInput


def test_mcp_literal_equals_server_enum():
    assert set(get_args(schemas.QueryMode)) == {m.value for m in ServerQueryMode}


def test_mcp_mode_schema_is_inline_enum_no_defs():
    schema = QueryInput.model_json_schema()
    mode = schema["properties"]["mode"]
    assert mode["type"] == "string"
    assert set(mode["enum"]) == {m.value for m in ServerQueryMode}
    assert "$defs" not in schema  # inline shape preserved (no $ref lift)


@pytest.mark.parametrize("mode", [m.value for m in ServerQueryMode])
def test_query_input_accepts_every_mode(mode):
    # Exactly the schema validation that rejected compute/scan/absence/timeline.
    assert QueryInput(query="x", mode=mode).mode == mode

# tests/rehome/test_io.py
import json

import pytest

from brainpalace_server.rehome._io import read_json, write_json_atomic


def test_write_then_read_roundtrips(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1, "b": "two"})
    assert read_json(p) == {"a": 1, "b": "two"}


def test_write_leaves_no_tempfile(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic(p, {"a": 1})
    assert [f.name for f in tmp_path.iterdir()] == ["x.json"]


def test_read_corrupt_raises(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        read_json(p)

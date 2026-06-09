"""Read-time layered config resolution: code < global < project, env on top."""

from __future__ import annotations

import textwrap

import pytest

from brainpalace_server.config import provider_config as pc


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Each test controls global + project explicitly. The conftest already
    empties the global layer + state dir; here we also pin XDG to this test's
    tmp_path and chdir to a clean dir so CWD walk-up finds no stray project."""
    monkeypatch.delenv("BRAINPALACE_CONFIG", raising=False)
    monkeypatch.delenv("DOC_SERVE_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    clean = tmp_path / "cwd"
    clean.mkdir()
    monkeypatch.chdir(clean)
    monkeypatch.setenv("BRAINPALACE_STATE_DIR", str(clean))
    pc.clear_settings_cache()
    yield
    pc.clear_settings_cache()


def _write_global(tmp_path, body: str) -> None:
    p = tmp_path / "xdg" / "brainpalace" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))


def _write_project(tmp_path, body: str) -> str:
    p = tmp_path / "proj" / ".brainpalace" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_deep_merge_project_wins_over_global():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    over = {"a": 9, "nested": {"y": 20, "z": 30}}
    assert pc._deep_merge(base, over) == {
        "a": 9,
        "nested": {"x": 1, "y": 20, "z": 30},
    }


def test_merged_dict_layers_global_under_project(tmp_path, monkeypatch):
    _write_global(
        tmp_path,
        """
        embedding:
          provider: cohere
          model: embed-english-v3.0
        bm25:
          language: de
        """,
    )
    proj = _write_project(
        tmp_path,
        """
        embedding:
          provider: openai
          model: text-embedding-3-large
        """,
    )
    monkeypatch.setenv("BRAINPALACE_CONFIG", proj)
    merged = pc.load_merged_config_dict()
    # project wins for embedding; global fills bm25.language; code fills the rest.
    assert merged["embedding"]["provider"] == "openai"
    assert merged["bm25"]["language"] == "de"


def test_load_provider_settings_inherits_global_when_project_absent(
    tmp_path, monkeypatch
):
    _write_global(
        tmp_path,
        """
        embedding:
          provider: cohere
          model: embed-english-v3.0
        """,
    )
    # No project file at all -> global supplies embedding, code supplies the rest.
    s = pc.load_provider_settings()
    assert s.embedding.provider == "cohere"
    # reranker absent everywhere -> code default present (does not raise).
    assert s.reranker is not None

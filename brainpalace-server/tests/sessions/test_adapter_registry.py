"""Registry contract for session tool adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.sessions.adapters import (
    all_adapters,
    get_adapter,
    register_adapter,
)
from brainpalace_server.sessions.adapters.base import SessionSource


class _FakeAdapter:
    slug = "fake-tool"

    def source_dirs(self, project_root: str, home: Path) -> list[Path]:
        return [home / ".fake" / "sessions"]

    def discover(self, src: Path, project_root: str) -> list[Path]:
        return sorted(src.glob("*.jsonl"))

    def owns(self, path: Path, project_root: str) -> bool:
        return True

    def parse(self, path: Path, *, text_trunc: int = 1500):
        raise NotImplementedError

    def title(self, path: Path, max_chars: int = 120) -> str | None:
        return None

    def is_subagent(self, path: Path) -> bool:
        return False

    def parent_session_id(self, path: Path) -> str | None:
        return None


def test_register_and_get_adapter():
    adapter = _FakeAdapter()
    register_adapter(adapter)
    assert get_adapter("fake-tool") is adapter
    assert adapter in all_adapters()


def test_get_adapter_unknown_slug_raises():
    with pytest.raises(KeyError):
        get_adapter("no-such-tool")


def test_session_source_pairs_adapter_with_dir(tmp_path):
    adapter = _FakeAdapter()
    src = SessionSource(adapter=adapter, directory=tmp_path)
    assert src.slug == "fake-tool"
    assert src.directory == tmp_path


def test_resolve_sources_autodetects_only_dirs_that_exist(tmp_path):
    from brainpalace_server.sessions.adapters import resolve_session_sources

    cc = tmp_path / ".claude" / "projects" / "-proj"
    cc.mkdir(parents=True)
    (cc / "s.jsonl").write_text("", encoding="utf-8")

    sources = resolve_session_sources("/proj", home=tmp_path)

    assert [s.slug for s in sources] == ["claude-code"]
    assert sources[0].directory == cc


def test_resolve_sources_skips_tools_with_no_directory(tmp_path):
    from brainpalace_server.sessions.adapters import resolve_session_sources

    sources = resolve_session_sources("/proj", home=tmp_path)

    assert sources == []


def test_explicit_tools_list_pins_selection(tmp_path):
    from brainpalace_server.sessions.adapters import resolve_session_sources

    cc = tmp_path / ".claude" / "projects" / "-proj"
    cc.mkdir(parents=True)

    assert resolve_session_sources("/proj", home=tmp_path, tools=[]) == []
    assert [
        s.slug
        for s in resolve_session_sources("/proj", home=tmp_path, tools=["claude-code"])
    ] == ["claude-code"]


def test_tool_dirs_overrides_the_resolved_directory(tmp_path):
    from brainpalace_server.sessions.adapters import resolve_session_sources

    custom = tmp_path / "elsewhere"
    custom.mkdir()

    sources = resolve_session_sources(
        "/proj",
        home=tmp_path,
        tools=["claude-code"],
        tool_dirs={"claude-code": str(custom)},
    )

    assert [s.directory for s in sources] == [custom]


def test_config_exposes_tools_and_tool_dirs():
    from brainpalace_server.config.session_config import SessionIndexingConfig

    cfg = SessionIndexingConfig()
    assert cfg.tools is None  # None = auto-detect
    assert cfg.tool_dirs == {}


def test_capabilities_carry_a_tuple_of_tools():
    from brainpalace_server.config.session_config import (
        SessionIndexingConfig,
        resolve_session_capabilities,
    )

    caps = resolve_session_capabilities(
        SessionIndexingConfig(), tools=("claude-code", "codex")
    )
    assert caps.tools == ("claude-code", "codex")
    assert caps.tool == "claude-code"  # deprecated single-value accessor

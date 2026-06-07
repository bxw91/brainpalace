"""Phase L (b) — skip-minified heuristic in DocumentLoader."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.indexing.document_loader import DocumentLoader


def test_min_js_filename_is_minified() -> None:
    assert DocumentLoader.is_minified("app.min.js", "var a=1;\n") is True


def test_min_css_filename_is_minified() -> None:
    assert DocumentLoader.is_minified("styles.min.css", "a{color:red}\n") is True


def test_normal_source_is_not_minified() -> None:
    src = "\n".join(f"def f{i}():\n    return {i}" for i in range(200))
    assert DocumentLoader.is_minified("module.py", src) is False


def test_single_huge_line_is_minified() -> None:
    text = "a" * 60_000  # one line, no newline, very long
    assert DocumentLoader.is_minified("bundle.js", text) is True


def test_large_low_newline_density_is_minified() -> None:
    # 80 KB with only a handful of newlines → generated/minified blob
    text = ("x" * 4000 + "\n") * 20  # lines of 4000 chars each
    assert DocumentLoader.is_minified("vendor.js", text) is True


def test_small_file_not_flagged() -> None:
    assert DocumentLoader.is_minified("tiny.js", "const x = 1;") is False


@pytest.mark.asyncio
async def test_load_from_folder_skips_minified_when_enabled(tmp_path: Path) -> None:
    (tmp_path / "app.min.js").write_text("var a=1;", encoding="utf-8")
    (tmp_path / "real.js").write_text(
        "\n".join(f"function f{i}() {{ return {i}; }}" for i in range(20)),
        encoding="utf-8",
    )
    loader = DocumentLoader(supported_extensions={".js"}, skip_minified=True)
    docs = await loader.load_from_folder(str(tmp_path))
    names = {Path(d.file_path).name for d in docs}
    assert "real.js" in names
    assert "app.min.js" not in names


@pytest.mark.asyncio
async def test_load_from_folder_keeps_minified_when_disabled(tmp_path: Path) -> None:
    (tmp_path / "app.min.js").write_text("var a=1;", encoding="utf-8")
    loader = DocumentLoader(supported_extensions={".js"}, skip_minified=False)
    docs = await loader.load_from_folder(str(tmp_path))
    names = {Path(d.file_path).name for d in docs}
    assert "app.min.js" in names

"""Tests for the Bash search-command analyzer used by the PreToolUse search guard.

Ported from the repo-dev analyzer's suite (.claude/hooks/test_search_guard_analyze.py)
and adapted to the library API: direct function calls, no subprocess protocol.
Covers spec D2 (manifest membership is scope truth; missing manifest -> allow),
D3 (recursion is the gate for grep; regex constructs route to grep), and D4
(pure_search drives enforce-deny eligibility).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brainpalace_cli.search_guard_bash import (
    BashSearchAnalysis,
    analyze_bash_command,
    is_indexed_target,
)


@pytest.fixture
def project(tmp_path: Path) -> dict:
    """Synthetic project: an indexed src/a.py + docs/d.md recorded in a folder
    manifest, plus an on-disk but NOT-indexed skip/x.py."""
    a_py = tmp_path / "src" / "a.py"
    a_py.parent.mkdir(parents=True)
    a_py.write_text("x = 1\n")
    d_md = tmp_path / "docs" / "d.md"
    d_md.parent.mkdir(parents=True)
    d_md.write_text("# d\n")
    x_py = tmp_path / "skip" / "x.py"
    x_py.parent.mkdir(parents=True)
    x_py.write_text("y = 2\n")

    manifests = tmp_path / ".brainpalace" / "manifests"
    manifests.mkdir(parents=True)
    files = {str(p.resolve()): {} for p in (a_py, d_md)}
    (manifests / "m.json").write_text(json.dumps({"files": files}))
    return {"root": tmp_path, "a_py": a_py, "d_md": d_md, "x_py": x_py}


def run(project: dict, command: str) -> BashSearchAnalysis:
    return analyze_bash_command(command, project["root"], cwd=project["root"])


# --- detection: recursion is the gate for grep; rg/ag always search ---------


def test_non_search_command(project):
    assert run(project, "ls -la").is_search is False


def test_single_file_grep_is_not_search(project):
    assert run(project, "grep -n foo src/a.py").is_search is False


def test_non_recursive_piped_grep_is_not_search(project):
    assert run(project, "grep foo src/a.py | head -20").is_search is False


def test_recursive_grep_is_search(project):
    r = run(project, "grep -rn foo src/")
    assert r.is_search is True
    assert r.term == "foo"
    assert r.classify == "bm25"
    assert r.target_indexed is True
    assert r.pure_search is True


def test_rg_is_search(project):
    r = run(project, "rg foo src/a.py")
    assert r.is_search is True
    assert r.term == "foo"
    assert r.target_indexed is True


@pytest.mark.parametrize(
    "flag", ["--include=*.py", "--include *.py"], ids=["equals", "space"]
)
def test_include_implies_recursive(project, flag):
    r = run(project, f"grep -n foo {flag} .")
    assert r.is_search is True
    assert r.term == "foo"


# --- classification (spec D3) -----------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [r"\d+", "[a-z]", "^foo", "foo.*bar", "ab{2,3}"],
    ids=["class-shorthand", "bracket", "anchor", "quantifier-star", "brace"],
)
def test_regex_constructs_classify_as_grep(project, pattern):
    r = run(project, f"grep -rn '{pattern}' src/")
    assert r.is_search is True
    assert r.classify == "grep"


def test_alternation_stays_bm25(project):
    r = run(project, r"grep -rn 'foo\|bar' src/")
    assert r.classify == "bm25"


# --- scope: manifest membership is the only truth (spec D2) -----------------


def test_unindexed_dir_target_not_indexed(project):
    r = run(project, "grep -rn foo skip/")
    assert r.is_search is True
    assert r.target_indexed is False


def test_outside_project_target_not_indexed(project):
    r = run(project, "grep -rn foo /nonexistent-elsewhere/")
    assert r.target_indexed is False


def test_no_path_defaults_to_cwd(project):
    r = run(project, "grep -rn foo")
    assert r.target_indexed is True  # cwd == project root, which contains indexed files


def test_relative_path_resolves_against_cwd(project):
    sub = project["root"] / "src"
    r = analyze_bash_command("grep -rn foo .", project["root"], cwd=sub)
    assert r.target_indexed is True


def test_missing_manifest_means_not_indexed(tmp_path: Path):
    (tmp_path / "src").mkdir()
    r = analyze_bash_command("grep -rn foo src/", tmp_path, cwd=tmp_path)
    assert r.is_search is True
    assert r.target_indexed is False  # fail-open toward allowing (spec D2)


# --- compound commands (spec D4 + dev-spec D1/D2 segmentation) --------------


def test_compound_two_greps_is_multi(project):
    r = run(project, "grep -rn foo src/; grep -rn bar docs/")
    assert r.is_search is True
    assert r.classify == "multi"
    assert r.pure_search is False


def test_compound_repro_pipe_semicolon_echo(project):
    cmd = (
        'grep -rn "mcp" src/a.py 2>/dev/null | head -20; '
        'echo "=== targets ==="; '
        'grep -rn "cursor\\|cline" docs/d.md'
    )
    r = run(project, cmd)
    assert r.is_search is True
    assert r.classify == "multi"


def test_grep_class_anywhere_wins(project):
    r = run(project, r"grep -rn foo src/ && grep -rn '\d+' docs/")
    assert r.classify == "grep"


def test_redirection_only_stays_pure(project):
    r = run(project, "grep -rn foo src/ 2>/dev/null")
    assert r.classify == "bm25"
    assert r.pure_search is True


def test_pipe_into_readonly_filter_stays_pure(project):
    r = run(project, "grep -rn foo src/ | head -20")
    assert r.pure_search is True


def test_side_effect_segment_breaks_purity(project):
    r = run(project, "grep -rn foo src/ && make test")
    assert r.is_search is True
    assert r.classify == "bm25"
    assert r.pure_search is False


def test_cd_prefix_breaks_purity(project):
    r = run(project, "cd src && grep -rn foo .")
    assert r.pure_search is False


# --- is_indexed_target: the Grep-tool scope check -----------------------------


def test_indexed_target_file(project):
    assert is_indexed_target("src/a.py", project["root"], project["root"]) is True


def test_indexed_target_dir(project):
    assert is_indexed_target("src", project["root"], project["root"]) is True


def test_indexed_target_unindexed_dir(project):
    assert is_indexed_target("skip", project["root"], project["root"]) is False


def test_indexed_target_none_means_cwd(project):
    assert is_indexed_target(None, project["root"], project["root"]) is True
    assert is_indexed_target(None, project["root"], project["root"] / "skip") is False


def test_indexed_target_missing_manifest(tmp_path):
    (tmp_path / "src").mkdir()
    assert is_indexed_target("src", tmp_path, tmp_path) is False

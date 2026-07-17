"""Tests for the search-guard Bash-command analyzer (search_guard_analyze.py).

Repo-dev tooling (project scope, not the shipped plugin). Runs the analyzer as
a subprocess against a synthetic project fixture (files + a folder manifest),
exactly as the bash hook invokes it: JSON on stdin, BP_ROOT env var, 5 stdout
lines (is_search, term, enforce, classify, scope).

Covers the compound-command parsing bug from
.planning/specs/2026-07-17-search-guard-compound-command-parsing.md: the
analyzer's operand loop used to run to the end of the whole command line, not
the end of one shell command, so `;`/`|`/redirections/a second `grep` all got
vacuumed up as bogus --file-paths globs (see the reproduction in that spec).

Before the D1-D4 fix (this file added in the same commit as the extraction,
step 2 of the plan of record): the compound/multi-segment cases below FAIL.
After the fix (step 3): they go green with no behavior change to the
already-correct single-segment cases.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_DIR = Path(__file__).resolve().parent
ANALYZER = HOOK_DIR / "search_guard_analyze.py"


@pytest.fixture
def project(tmp_path):
    """A synthetic project: a few indexed files + a folder manifest, laid out
    to mirror the spec's real reproduction (brainpalace-cli/.../init.py and
    docs/MCP_SETUP.md), plus two flat files (a.py/b.py) for the simpler cases.
    """
    init_py = tmp_path / "brainpalace-cli" / "brainpalace_cli" / "commands" / "init.py"
    init_py.parent.mkdir(parents=True)
    init_py.write_text("# init\n")

    mcp_setup = tmp_path / "docs" / "MCP_SETUP.md"
    mcp_setup.parent.mkdir(parents=True)
    mcp_setup.write_text("# mcp setup\n")

    a_py = tmp_path / "a.py"
    a_py.write_text("print('a')\n")
    b_py = tmp_path / "b.py"
    b_py.write_text("print('b')\n")

    manifests_dir = tmp_path / ".brainpalace" / "manifests"
    manifests_dir.mkdir(parents=True)
    files = {
        str(p.resolve()): {}
        for p in (init_py, mcp_setup, a_py, b_py)
    }
    (manifests_dir / "m.json").write_text(json.dumps({"files": files}))

    return {
        "root": tmp_path,
        "init_py": init_py,
        "mcp_setup": mcp_setup,
        "a_py": a_py,
        "b_py": b_py,
    }


def run_analyzer(root, tool_name, tool_input):
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    env = dict(os.environ)
    env["BP_ROOT"] = str(root)
    proc = subprocess.run(
        [sys.executable, str(ANALYZER)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    lines = proc.stdout.splitlines()
    while len(lines) < 5:
        lines.append("")
    is_search, term, enforce, classify, scope = lines[:5]
    return {
        "is_search": is_search,
        "term": term,
        "enforce": enforce,
        "classify": classify,
        "scope": scope,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }


def rel(root, p):
    return str(Path(p).relative_to(root))


# --- the exact spec reproduction: two grep invocations joined by |, ;, echo --


def test_compound_command_repro_is_clean(project):
    root = project["root"]
    cmd = (
        'grep -rn "mcp" {init} 2>/dev/null | head -20; '
        'echo "=== targets ==="; '
        'grep -rn "cursor\\|cline" {mcp}'
    ).format(init=rel(root, project["init_py"]), mcp=rel(root, project["mcp_setup"]))

    r = run_analyzer(root, "Bash", {"command": cmd})

    assert r["is_search"] == "1"
    # Two independent bm25-routable search segments survive (D3: neither
    # pattern is grep-class) -> D4: ALLOW the whole call rather than denying
    # on half an answer.
    assert r["classify"] == "multi"
    # No garbage from the pipe, the redirection, echo, or the second grep's
    # own name/pattern should ever land in scope.
    garbage = ["|*", "head*", "echo*", "=== targets", "2>/dev/null", ";*"]
    for bad in garbage:
        assert bad not in r["scope"], f"garbage {bad!r} leaked into scope: {r['scope']!r}"


# --- single grep + path: must stay exactly correct (regression guard) -------


def test_single_grep_plus_path(project):
    root = project["root"]
    r = run_analyzer(root, "Bash", {"command": f'grep -rn foo {rel(root, project["a_py"])}'})
    assert r["is_search"] == "1"
    assert r["term"] == "foo"
    assert r["classify"] == "bm25"
    assert r["enforce"] == "1"
    assert r["scope"] == str(project["a_py"].resolve()) + "*"


# --- --include=V and --include V forms ---------------------------------------


@pytest.mark.parametrize(
    "flag",
    ["--include=*.py", "--include *.py"],
    ids=["include-equals", "include-space"],
)
def test_include_forms(project, flag):
    root = project["root"]
    cmd = f'grep -rn foo {flag} .'
    r = run_analyzer(root, "Bash", {"command": cmd})
    assert r["is_search"] == "1"
    assert r["term"] == "foo"
    assert r["classify"] == "bm25"
    assert r["scope"].endswith("*.py")


# --- D3 regex-class patterns: must be grep-classified, not bm25 -------------


@pytest.mark.parametrize("pattern", [r"\d+", "[a-z]", "^foo"], ids=["backslash-d", "bracket-class", "anchor"])
def test_regex_class_routes_to_grep(project, pattern):
    root = project["root"]
    r = run_analyzer(root, "Bash", {"command": f'grep -rn "{pattern}" {rel(root, project["a_py"])}'})
    assert r["is_search"] == "1"
    assert r["classify"] == "grep"


# --- redirection-only: a trailing redirect on an otherwise-clean grep -------


def test_redirection_only(project):
    root = project["root"]
    cmd = f'grep -rn foo {rel(root, project["a_py"])} 2>/dev/null'
    r = run_analyzer(root, "Bash", {"command": cmd})
    assert r["is_search"] == "1"
    assert r["term"] == "foo"
    assert r["classify"] == "bm25"
    assert r["enforce"] == "1"
    assert r["scope"] == str(project["a_py"].resolve()) + "*"


# --- two-grep compound (plain `;`, no pipe/redirect noise) ------------------


def test_two_grep_compound(project):
    root = project["root"]
    cmd = 'grep -rn foo {a}; grep -rn bar {b}'.format(
        a=rel(root, project["a_py"]), b=rel(root, project["b_py"])
    )
    r = run_analyzer(root, "Bash", {"command": cmd})
    assert r["is_search"] == "1"
    assert r["classify"] == "multi"
    assert "grep*" not in r["scope"]
    assert ";" not in r["scope"]


# --- piped recursive grep: D5 says this STAYS intercepted -------------------


def test_piped_recursive_grep_is_intercepted(project):
    root = project["root"]
    cmd = f'grep -rn foo {rel(root, project["a_py"])} | head -20'
    r = run_analyzer(root, "Bash", {"command": cmd})
    assert r["is_search"] == "1"
    assert r["term"] == "foo"
    assert r["classify"] == "bm25"
    assert r["enforce"] == "1"
    assert r["scope"] == str(project["a_py"].resolve()) + "*"


# --- non-recursive piped grep: must NOT be treated as search ----------------


def test_non_recursive_piped_grep_is_not_search(project):
    root = project["root"]
    cmd = f'grep foo {rel(root, project["a_py"])} | head -20'
    r = run_analyzer(root, "Bash", {"command": cmd})
    assert r["is_search"] == "0"


# --- rg -----------------------------------------------------------------


def test_rg(project):
    root = project["root"]
    r = run_analyzer(root, "Bash", {"command": f'rg foo {rel(root, project["a_py"])}'})
    assert r["is_search"] == "1"
    assert r["term"] == "foo"
    assert r["classify"] == "bm25"
    assert r["enforce"] == "1"
    assert r["scope"] == str(project["a_py"].resolve()) + "*"


# --- Glob passthrough: is_search must stay 0 (category error per A15) ------


def test_glob_passthrough(project):
    root = project["root"]
    r = run_analyzer(root, "Glob", {"pattern": "**/*.py"})
    assert r["is_search"] == "0"

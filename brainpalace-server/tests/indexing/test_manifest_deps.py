from brainpalace_server.indexing.manifest_deps import (
    extract_manifest_deps,
    is_manifest,
)

PYPROJECT = """
[tool.poetry]
name = "myserver"

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.111"
pydantic = "^2.7"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
"""

PEP621 = """
[project]
name = "mytool"
dependencies = ["requests>=2.31", "click"]
"""

PACKAGE_JSON = """
{
  "name": "mydash",
  "dependencies": {"react": "^18.0.0"},
  "devDependencies": {"vitest": "^1.0.0"}
}
"""


def _deps(triples):
    return {
        (t.effective_subject_id, t.effective_object_id)
        for t in triples
        if t.predicate == "depends_on"
    }


def test_is_manifest():
    assert is_manifest("a/b/pyproject.toml")
    assert is_manifest("web/package.json")
    assert not is_manifest("a/b/config.toml")


def test_poetry_deps_python_excluded():
    triples = extract_manifest_deps("srv/pyproject.toml", PYPROJECT)
    deps = _deps(triples)
    assert ("myserver", "fastapi") in deps
    assert ("myserver", "pydantic") in deps
    assert ("myserver", "pytest") in deps  # dev group included
    assert not any(o == "python" for _, o in deps)
    t = triples[0]
    assert t.subject_type == "Package" and t.object_type == "Package"
    assert t.source_file == "srv/pyproject.toml"


def test_pep621_deps_specifiers_stripped():
    deps = _deps(extract_manifest_deps("t/pyproject.toml", PEP621))
    assert ("mytool", "requests") in deps
    assert ("mytool", "click") in deps


def test_package_json_deps():
    deps = _deps(extract_manifest_deps("web/package.json", PACKAGE_JSON))
    assert ("mydash", "react") in deps
    assert ("mydash", "vitest") in deps


def test_malformed_manifest_returns_empty():
    assert extract_manifest_deps("x/pyproject.toml", "not [ toml") == []
    assert extract_manifest_deps("x/package.json", "{oops") == []

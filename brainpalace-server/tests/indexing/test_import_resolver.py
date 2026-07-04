from brainpalace_server.indexing.import_resolver import resolve_import


def _mk(tmp_path, rel, text="x = 1\n"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return str(p).replace("\\", "/")


def test_absolute_import_resolves_to_repo_file(tmp_path):
    target = _mk(tmp_path, "proj/pkg/util.py")
    importer = _mk(tmp_path, "proj/main.py")
    assert resolve_import(importer, "pkg.util", 0, [], root=str(tmp_path)) == [target]


def test_absolute_import_package_init(tmp_path):
    target = _mk(tmp_path, "proj/pkg/__init__.py")
    importer = _mk(tmp_path, "proj/main.py")
    assert resolve_import(importer, "pkg", 0, [], root=str(tmp_path)) == [target]


def test_from_import_name_is_submodule(tmp_path):
    target = _mk(tmp_path, "proj/pkg/sub.py")
    _mk(tmp_path, "proj/pkg/__init__.py")
    importer = _mk(tmp_path, "proj/main.py")
    hits = resolve_import(importer, "pkg", 0, ["sub"], root=str(tmp_path))
    assert target in hits


def test_from_import_name_is_a_class_falls_back_to_module(tmp_path):
    target = _mk(tmp_path, "proj/pkg/models.py")
    importer = _mk(tmp_path, "proj/main.py")
    hits = resolve_import(importer, "pkg.models", 0, ["Widget"], root=str(tmp_path))
    assert hits == [target]


def test_relative_import_anchored(tmp_path):
    target = _mk(tmp_path, "proj/pkg/util.py")
    importer = _mk(tmp_path, "proj/pkg/mod.py")
    assert resolve_import(importer, "util", 1, [], root=str(tmp_path)) == [target]


def test_relative_level2_goes_up(tmp_path):
    target = _mk(tmp_path, "proj/common.py")
    importer = _mk(tmp_path, "proj/pkg/mod.py")
    assert resolve_import(importer, "common", 2, [], root=str(tmp_path)) == [target]


def test_external_import_returns_empty(tmp_path):
    importer = _mk(tmp_path, "proj/main.py")
    assert resolve_import(importer, "os", 0, [], root=str(tmp_path)) == []


def test_never_resolves_to_self(tmp_path):
    importer = _mk(tmp_path, "proj/main.py")
    assert resolve_import(importer, "main", 0, [], root=str(tmp_path)) == []

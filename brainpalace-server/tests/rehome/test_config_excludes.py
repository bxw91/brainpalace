import yaml

from brainpalace_server.rehome.config_excludes import rehome_project_excludes


def test_rehome_project_excludes_swaps_absolute_in_root(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "indexing": {
                    "exclude_patterns": ["/old/root/build", "**/node_modules/**"]
                },
                "provider": {"embedding": "openai"},
            }
        )
    )
    n = rehome_project_excludes(tmp_path, "/old/root", "/new/home")
    assert n == 1
    data = yaml.safe_load(cfg.read_text())
    assert data["indexing"]["exclude_patterns"] == [
        "/new/home/build",
        "**/node_modules/**",
    ]
    assert data["provider"] == {"embedding": "openai"}  # untouched


def test_rehome_project_excludes_noop_when_no_in_root(tmp_path):
    cfg = tmp_path / "config.yaml"
    original = yaml.safe_dump({"indexing": {"exclude_patterns": ["*.log"]}})
    cfg.write_text(original)
    assert rehome_project_excludes(tmp_path, "/old/root", "/new/home") == 0
    assert cfg.read_text() == original  # byte-identical, not rewritten


def test_rehome_project_excludes_missing_file(tmp_path):
    assert rehome_project_excludes(tmp_path, "/old/root", "/new/home") == 0

from brainpalace_cli.doc_sync.checkers.config import ConfigChecker
from brainpalace_cli.doc_sync.facts import InterfaceSnapshot

# config_keys include valid dotpaths + section names (mirrors config_dotpaths()).
SNAP = InterfaceSnapshot(
    1,
    "9.9.9",
    config_keys=[
        "embedding",
        "bm25",
        "dashboard",
        "embedding.provider",
        "bm25.language",
    ],
)


def test_dangling_config_key_flagged(tmp_path):
    d = tmp_path / "configuration-guide.md"
    d.write_text("Set `embedding.provder` (typo) and `bm25.language`.\n")
    recs = ConfigChecker(doc_roots=[tmp_path]).check(SNAP)
    bad = {r.source_id for r in recs}
    assert "embedding.provder" in bad  # real section, bad field
    assert "bm25.language" not in bad


def test_valid_config_keys_clean(tmp_path):
    d = tmp_path / "x.md"
    d.write_text("`embedding.provider` and `bm25.language` are valid.\n")
    assert ConfigChecker(doc_roots=[tmp_path]).check(SNAP) == []


def test_filenames_and_modules_not_flagged(tmp_path):
    # The dangerous false-positive class — none of these are config keys.
    d = tmp_path / "x.md"
    d.write_text(
        "Files `config.yaml`, `dashboard.json`, `auth.py`; calls `click.confirm`; "
        "module `brainpalace_cli.mcp_server`; date `dd.mm.yyyy`.\n"
    )
    recs = ConfigChecker(doc_roots=[tmp_path]).check(SNAP)
    assert recs == []  # config.* not a section; dashboard.json is file-ext; etc.

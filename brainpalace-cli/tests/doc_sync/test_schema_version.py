import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "check_doc_sync", REPO / "scripts" / "check_doc_sync.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_assert_schema_version_passes_on_match():
    from brainpalace_cli.doc_sync import SCHEMA_VERSION

    mod.assert_schema_version({"schema_version": SCHEMA_VERSION})  # no raise


def test_assert_schema_version_fails_loudly_on_mismatch():
    import pytest

    with pytest.raises(SystemExit):
        mod.assert_schema_version({"schema_version": 999})

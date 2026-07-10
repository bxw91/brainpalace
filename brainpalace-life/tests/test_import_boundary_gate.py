"""The import-boundary gate: seams pass; internals, cli, dynamic imports, and
direct engine-data access fail. Black-box via subprocess over temp fixtures."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_import_boundary.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def _pkg(tmp_path: Path, name: str, body: str) -> Path:
    pkg = tmp_path / "brainpalace_life"
    pkg.mkdir(exist_ok=True)
    (pkg / name).write_text(body)
    return pkg


def test_seam_imports_pass_both_forms(tmp_path: Path):
    # deep form AND package form of the same seam — both must pass (the
    # `from a.b import c` form is the one a naive checker false-positives).
    root = _pkg(
        tmp_path,
        "ok.py",
        "from brainpalace_server.ingestion.adapter import SourceAdapter\n"
        "from brainpalace_server.ingestion import adapter, sink\n"
        "from brainpalace_server.models import record\n"
        "from brainpalace_server.models.record import Record\n"
        "from brainpalace_server.services.query_service import QueryService\n"
        "import brainpalace_server.indexing.salience as s\n"
        "import os\n"
        "DB = 'my_life_cache.sqlite'\n",  # product's own artifact — allowed
    )
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_internal_storage_import_fails(tmp_path: Path):
    root = _pkg(
        tmp_path,
        "bad.py",
        "from brainpalace_server.storage.record_store import RecordStore\n",
    )
    result = _run(root)
    assert result.returncode == 1
    assert "storage.record_store" in result.stdout and "bad.py" in result.stdout


def test_denied_service_import_fails(tmp_path: Path):
    root = _pkg(
        tmp_path,
        "bad2.py",
        "import brainpalace_server.services.memory_service as m\n",
    )
    result = _run(root)
    assert result.returncode == 1
    assert "services.memory_service" in result.stdout


def test_from_package_internal_fails(tmp_path: Path):
    # `from brainpalace_server.storage import record_store` — the package form
    # of a DENIED import must still fail (mirror of the seam package-form pass).
    root = _pkg(
        tmp_path,
        "bad3.py",
        "from brainpalace_server.storage import record_store\n",
    )
    assert _run(root).returncode == 1


def test_cli_import_fails(tmp_path: Path):
    # product has no CLI dependency — any brainpalace_cli import is forbidden.
    root = _pkg(tmp_path, "bad4.py", "from brainpalace_cli.client import api_client\n")
    result = _run(root)
    assert result.returncode == 1 and "brainpalace_cli" in result.stdout


def test_dynamic_import_of_internal_fails(tmp_path: Path):
    root = _pkg(
        tmp_path,
        "bad5.py",
        "import importlib\n"
        "m = importlib.import_module(\n"
        "    'brainpalace_server.storage.sqlite_graph_store'\n"
        ")\n",
    )
    result = _run(root)
    assert result.returncode == 1 and "sqlite_graph_store" in result.stdout


def test_direct_engine_db_access_fails(tmp_path: Path):
    # the roadmap's canonical bypass: reaching into graph_store.db directly.
    # Not an import — caught by the data-artifact string rule.
    root = _pkg(
        tmp_path,
        "bad6.py",
        "import sqlite3\n" "c = sqlite3.connect('.brainpalace/graph_store.db')\n",
    )
    result = _run(root)
    assert result.returncode == 1
    assert "graph_store.db" in result.stdout or ".brainpalace" in result.stdout


def test_syntax_error_fails_cleanly(tmp_path: Path):
    root = _pkg(tmp_path, "broken.py", "def (:\n")  # invalid syntax
    result = _run(root)
    assert result.returncode == 1
    assert "broken.py" in (result.stdout + result.stderr)
    assert "Traceback" not in result.stderr  # clean failure, not a crash


def test_clean_product_code_passes(tmp_path: Path):
    root = _pkg(
        tmp_path,
        "fine.py",
        "import os\nimport json\n\n\ndef f() -> int:\n    return 1\n",
    )
    assert _run(root).returncode == 0


def test_lookalike_paths_do_not_false_positive(tmp_path: Path):
    # segment-anchored matching: the product's OWN dir/db and near-miss basenames
    # must NOT trip R2 (substring matching used to catch all of these).
    root = _pkg(
        tmp_path,
        "own.py",
        "A = '.brainpalace_life/cache.db'\n"  # product's own dir
        "B = 'old_records.db'\n"  # near-miss basename
        "C = 'data/myself.db'\n",  # contains 'self.db' as a substring
    )
    assert _run(root).returncode == 0, _run(root).stdout


def test_docstring_prose_naming_artifacts_passes(tmp_path: Path):
    # boundary prose in a docstring names engine artifacts on purpose — the gate
    # must not flag its own documentation.
    root = _pkg(
        tmp_path,
        "doc.py",
        '"""Never open .brainpalace/graph_store.db directly; persist via seams."""\n'
        "\n\ndef f() -> int:\n    return 1\n",
    )
    assert _run(root).returncode == 0, _run(root).stdout


def test_docstring_exclusion_does_not_hide_real_access(tmp_path: Path):
    # a real path literal in code is still caught even when a docstring precedes it.
    root = _pkg(
        tmp_path,
        "mix.py",
        '"""Module doc."""\n'
        "import sqlite3\n"
        "c = sqlite3.connect('.brainpalace/records.db')\n",
    )
    result = _run(root)
    assert result.returncode == 1 and "records.db" in result.stdout


def test_verify_seams_against_live_engine():
    # the allowlist is otherwise doc-vs-doc: this imports every seam against the
    # installed engine (this venv force-installs the worktree server) so a
    # renamed/moved seam fails the suite instead of leaving the gate green.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-seams"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

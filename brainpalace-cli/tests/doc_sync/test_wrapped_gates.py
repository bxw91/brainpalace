import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "check_doc_sync", REPO / "scripts" / "check_doc_sync.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_run_wrapped_gates_returns_zero_on_repo():
    # The real repo gates are green post-merge; wrapping them returns 0.
    rc = mod.run_wrapped_gates()
    assert rc == 0

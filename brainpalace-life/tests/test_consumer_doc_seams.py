"""BUILDING_ON_BRAINPALACE.md's seam table must list exactly the live
import-boundary allowlist (spec Item 4: never hand-maintained)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_import_boundary import ALLOWED_SEAMS  # noqa: E402

DOC = REPO / "docs" / "BUILDING_ON_BRAINPALACE.md"


def test_doc_exists():
    assert DOC.exists(), "docs/BUILDING_ON_BRAINPALACE.md missing"


def test_every_seam_is_documented():
    text = DOC.read_text(encoding="utf-8")
    missing = [s for s in ALLOWED_SEAMS if f"`{s}`" not in text]
    assert not missing, f"seams missing from the doc: {missing}"


def test_no_stale_seams_documented():
    text = DOC.read_text(encoding="utf-8")
    import re

    documented = set(re.findall(r"`(brainpalace_server\.[a-z_.]+)`", text))
    stale = {
        d
        for d in documented
        if not any(d == s or d.startswith(s + ".") for s in ALLOWED_SEAMS)
    }
    assert not stale, f"doc names non-seam modules as supported: {stale}"

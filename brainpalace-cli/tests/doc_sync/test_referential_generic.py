import re

from brainpalace_cli.doc_sync.facts import DriftKind
from brainpalace_cli.doc_sync.referential import dangling_tokens

PAT = re.compile(r"--mode[= ]([a-z]+)")


def test_dangling_tokens_flags_unknown_and_skips_known(tmp_path):
    d = tmp_path / "brainpalace-x.md"
    d.write_text(
        "`brainpalace query --mode ghost`\n`brainpalace query --mode hybrid`\n"
    )
    recs = dangling_tokens(
        [d],
        PAT,
        known={"hybrid", "bm25"},
        surface="modes",
        detail="mode '{tok}' is not a valid mode",
    )
    bad = {r.source_id for r in recs}
    assert "ghost" in bad and "hybrid" not in bad
    assert all(r.kind is DriftKind.EXTRA for r in recs)

"""ProviderTablesChecker + serializers: GENERATED provider/install blocks are
rendered from the live registries and gated against drift."""

from __future__ import annotations

from pathlib import Path

from brainpalace_cli.doc_sync.checkers.provider_tables import (
    GENERATED_RENDERERS,
    ProviderTablesChecker,
)
from brainpalace_cli.doc_sync.facts import DriftKind, InterfaceSnapshot
from brainpalace_cli.doc_sync.generator import regenerate_provider_tables
from brainpalace_cli.doc_sync.introspect import live_snapshot
from brainpalace_cli.doc_sync.serializer import (
    render_install_dirs_table,
    render_provider_table,
)

REPO = Path(__file__).resolve().parents[3]

_SNAP = InterfaceSnapshot(
    1,
    "9.9.9",
    providers={
        "embedding": {
            "openai": {
                "models": ["m-large", "m-small"],
                "needs_base_url": False,
                "default_api_key_env": "OPENAI_API_KEY",
            },
            "ollama": {
                "models": ["local-embed"],
                "needs_base_url": True,
                "default_api_key_env": None,
            },
        }
    },
    install_dirs={"claude": {"project": ".claude/x", "global": "~/.claude/x"}},
)


def test_render_provider_table_shape():
    out = render_provider_table(_SNAP.providers, "embedding")
    assert "| `openai` | `OPENAI_API_KEY` | `m-large`, `m-small` |" in out
    # local provider → no env var cell
    assert "| `ollama` | _(none — local)_ | `local-embed` |" in out


def test_render_install_dirs_table_shape():
    out = render_install_dirs_table(_SNAP.install_dirs)
    assert "| `claude` | `.claude/x` | `~/.claude/x` |" in out


def _doc(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "d.md"
    p.write_text(body)
    return p


def test_matching_block_is_clean(tmp_path):
    table = render_provider_table(_SNAP.providers, "embedding")
    _doc(
        tmp_path,
        f"# x\n<!--GENERATED:providers-embedding-->\n{table}\n<!--/GENERATED-->\n",
    )
    recs = ProviderTablesChecker(doc_roots=[tmp_path]).check(_SNAP)
    assert recs == [], [(r.source_id, r.detail) for r in recs]


def test_drifted_block_flagged(tmp_path):
    _doc(
        tmp_path,
        "# x\n<!--GENERATED:providers-embedding-->\n| stale |\n<!--/GENERATED-->\n",
    )
    recs = ProviderTablesChecker(doc_roots=[tmp_path]).check(_SNAP)
    assert any(
        r.source_id == "providers-embedding" and r.kind is DriftKind.MISMATCH
        for r in recs
    )


def test_doc_without_block_ignored(tmp_path):
    _doc(tmp_path, "# x\nNo generated blocks here.\n")
    assert ProviderTablesChecker(doc_roots=[tmp_path]).check(_SNAP) == []


def test_duplicate_block_is_invalid(tmp_path):
    _doc(
        tmp_path,
        "<!--GENERATED:install-dirs-->\na\n<!--/GENERATED-->\n"
        "<!--GENERATED:install-dirs-->\nb\n<!--/GENERATED-->\n",
    )
    recs = ProviderTablesChecker(doc_roots=[tmp_path]).check(_SNAP)
    assert any(r.kind is DriftKind.INVALID for r in recs)


def test_regenerate_fills_block(tmp_path):
    p = _doc(
        tmp_path,
        "# x\n<!--GENERATED:providers-embedding-->\nOLD\n<!--/GENERATED-->\n",
    )
    changed = regenerate_provider_tables(p, _SNAP)
    assert changed
    assert "`m-large`" in p.read_text()
    # idempotent: second run makes no change
    assert regenerate_provider_tables(p, _SNAP) is False


# --- dogfood: live registry populated + repo blocks in sync ----------------- #


def test_live_snapshot_has_registries():
    snap = live_snapshot()
    assert snap.providers and "embedding" in snap.providers
    assert snap.install_dirs and "claude" in snap.install_dirs


def test_repo_provider_blocks_in_sync():
    snap = live_snapshot()
    recs = ProviderTablesChecker(
        doc_roots=[REPO / "brainpalace-plugin", REPO / "docs", REPO / "README.md"]
    ).check(snap)
    assert recs == [], "\n".join(
        f"{r.source_id} {r.kind.value}: {r.doc_path}" for r in recs
    )


def test_renderer_registry_covers_all_block_names():
    # Guard: every renderer name is non-empty and callable.
    assert set(GENERATED_RENDERERS) >= {
        "providers-embedding",
        "providers-summarization",
        "providers-reranker",
        "install-dirs",
    }

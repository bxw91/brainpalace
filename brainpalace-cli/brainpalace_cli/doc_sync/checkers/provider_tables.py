"""Provider/install tables surface: machine-owned GENERATED blocks whose content is
rendered from the LIVE canonical registries — `brainpalace_cli.providers.PROVIDERS`
(models + api-key env var per provider) and `install_agent.INSTALL_DIRS` (per-runtime
install paths). This is the "change code → docs change" path for those facts: edit
the registry, run `sync-docs --fix`, and every block regenerates; the gate fails if
a block drifts from the registry.

Block names → renderers live in `GENERATED_RENDERERS` (also used by the fix path).
The checker recursively scans the given doc roots, so a NEW doc that adds one of
these blocks is covered automatically — no list to maintain.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from brainpalace_cli.doc_sync.facts import DriftKind, DriftRecord, InterfaceSnapshot
from brainpalace_cli.doc_sync.markers import OPEN_FMT, MarkerError, find_block
from brainpalace_cli.doc_sync.serializer import (
    render_install_dirs_table,
    render_provider_table,
)

SURFACE = "provider-tables"

#: GENERATED block name -> renderer(snapshot) -> markdown body. The single registry
#: shared by the checker (compare) and the generator (regenerate).
GENERATED_RENDERERS: dict[str, Callable[[InterfaceSnapshot], str]] = {
    "providers-embedding": lambda s: render_provider_table(s.providers, "embedding"),
    "providers-summarization": lambda s: render_provider_table(
        s.providers, "summarization"
    ),
    "providers-reranker": lambda s: render_provider_table(s.providers, "reranker"),
    "install-dirs": lambda s: render_install_dirs_table(s.install_dirs),
}


class ProviderTablesChecker:
    surface = SURFACE

    def __init__(self, doc_roots: Iterable[Path]) -> None:
        self.doc_roots = [Path(r) for r in doc_roots]

    def _docs(self) -> list[Path]:
        out: set[Path] = set()
        for root in self.doc_roots:
            if root.is_file() and root.suffix == ".md":
                out.add(root)
            elif root.is_dir():
                out.update(root.rglob("*.md"))
        return sorted(out)

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        records: list[DriftRecord] = []
        for path in self._docs():
            text = path.read_text(encoding="utf-8")
            for name, render in GENERATED_RENDERERS.items():
                if OPEN_FMT.format(name=name) not in text:
                    continue  # block not present in this doc — nothing to gate
                try:
                    inner = find_block(text, name)
                except MarkerError as exc:  # duplicate / unbalanced markers
                    records.append(
                        DriftRecord(
                            SURFACE, name, str(path), DriftKind.INVALID, str(exc)
                        )
                    )
                    continue
                if inner.strip() != render(snap).strip():
                    records.append(
                        DriftRecord(
                            SURFACE,
                            name,
                            str(path),
                            DriftKind.MISMATCH,
                            f"GENERATED:{name} block out of sync with live registry",
                        )
                    )
        return records

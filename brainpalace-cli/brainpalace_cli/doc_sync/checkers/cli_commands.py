"""CLI-commands checker. Gates the CONTRACT in command-doc frontmatter against the
live Click group. Meta-check: every live (non-hidden, non-allowlisted) command has a
doc, and every doc maps to a live command or an allowlist entry."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from brainpalace_cli.doc_sync.allowlist import (
    DOCUMENTED_ALIASES,
    PLUGIN_ONLY_COMMAND_DOCS,
    UNDOCUMENTED_COMMANDS,
)
from brainpalace_cli.doc_sync.facts import (
    CommandFact,
    DriftKind,
    DriftRecord,
    FlagFact,
    InterfaceSnapshot,
    canon_default,
)
from brainpalace_cli.doc_sync.markers import MarkerError, find_block
from brainpalace_cli.doc_sync.referential import dangling_tokens
from brainpalace_cli.doc_sync.serializer import render_flags_table

SURFACE = "cli"

# Match a real `brainpalace <subcommand>` INVOCATION (resolution H: scoped to
# invocations, not any mention). `brainpalace` must sit in command position — at the
# start of a line (optionally after a shell prompt/indent), after a shell separator
# (| & ; ( $( ), or at the start of an inline-code span (backtick). This rejects
# arg/prose uses like `conda create -n brainpalace python` or `Using brainpalace at:`
# where `brainpalace` is an env-name/word, not the command. Same-line gap only.
_INVOKE_RE = re.compile(
    r"(?:^|[`(;|&]|\$\(|[$#>][ \t])[ \t]*brainpalace[ \t]+([a-z][a-z0-9-]+)",
    re.MULTILINE,
)
_GLOBAL_FLAGS = {"--help", "--version"}


def referential_drift(
    docs: Sequence[Path | str], live_commands: set[str]
) -> list[DriftRecord]:
    """Flag `brainpalace <cmd>` invocations naming a command that does not exist."""
    known = (
        set(live_commands)
        | set(UNDOCUMENTED_COMMANDS)
        | set(DOCUMENTED_ALIASES)
        | set(PLUGIN_ONLY_COMMAND_DOCS)
        | _GLOBAL_FLAGS
    )
    return dangling_tokens(
        docs,
        _INVOKE_RE,
        known,
        SURFACE,
        "prose/example references unknown command '{tok}'",
    )


def _doc_path(docs_dir: Path, cmd: str) -> Path:
    return docs_dir / f"brainpalace-{cmd}.md"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        raise ValueError("no frontmatter")
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm) or {}


def _read_frontmatter(path: Path) -> dict[str, Any]:
    return _parse_frontmatter(path.read_text(encoding="utf-8"))


def _doc_flag_facts(fm: dict[str, Any]) -> dict[str, FlagFact]:
    out: dict[str, FlagFact] = {}
    for p in fm.get("parameters") or []:
        name = str(p.get("name"))
        out[name] = FlagFact(
            name=name,
            type=str(p.get("type", "text")),
            default=canon_default(p.get("default")),
            required=bool(p.get("required", False)),
        )
    return out


class CliCommandsChecker:
    surface = SURFACE

    def __init__(self, docs_dir: Path) -> None:
        self.docs_dir = Path(docs_dir)

    def _live_documentable(self, snap: InterfaceSnapshot) -> dict[str, CommandFact]:
        return {
            c.name: c
            for c in snap.commands
            if not c.hidden and c.name not in UNDOCUMENTED_COMMANDS
        }

    def _doc_commands(self) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for p in sorted(self.docs_dir.glob("brainpalace-*.md")):
            cmd = p.stem[len("brainpalace-") :]
            if cmd in DOCUMENTED_ALIASES or cmd in PLUGIN_ONLY_COMMAND_DOCS:
                # Plugin slash-command docs aren't CLI mirrors — not gated here.
                continue
            out[cmd] = p
        return out

    def check(self, snap: InterfaceSnapshot) -> list[DriftRecord]:
        records: list[DriftRecord] = []
        live = self._live_documentable(snap)
        docs = self._doc_commands()

        missing = sorted(set(live) - set(docs))
        extra = [
            n for n in sorted(set(docs) - set(live)) if n not in UNDOCUMENTED_COMMANDS
        ]
        if len(missing) == 1 and len(extra) == 1:
            old, new = extra[0], missing[0]
            records.append(
                DriftRecord(
                    SURFACE,
                    new,
                    str(docs[old]),
                    DriftKind.RENAME,
                    f"{old} -> {new}?",
                )
            )
        else:
            for name in missing:
                records.append(
                    DriftRecord(
                        SURFACE,
                        name,
                        str(_doc_path(self.docs_dir, name)),
                        DriftKind.MISSING,
                        "live command has no doc",
                    )
                )
            for name in extra:
                records.append(
                    DriftRecord(
                        SURFACE,
                        name,
                        str(docs[name]),
                        DriftKind.EXTRA,
                        "doc for non-existent command",
                    )
                )

        for name in sorted(set(live) & set(docs)):
            text = docs[name].read_text(encoding="utf-8")
            try:
                fm = _parse_frontmatter(text)
            except Exception as exc:  # noqa: BLE001
                records.append(
                    DriftRecord(
                        SURFACE,
                        name,
                        str(docs[name]),
                        DriftKind.INVALID,
                        f"frontmatter: {exc}",
                    )
                )
                continue
            live_flags = {f.name: f for f in live[name].flags}
            doc_flags = _doc_flag_facts(fm)
            if live_flags != doc_flags:
                detail = (
                    f"contract differs: live={sorted(live_flags)} "
                    f"doc={sorted(doc_flags)}"
                )
                records.append(
                    DriftRecord(
                        SURFACE, name, str(docs[name]), DriftKind.MISMATCH, detail
                    )
                )

            try:
                inner = find_block(text, "flags")
            except MarkerError:
                inner = None  # no body block (allowed: frontmatter is the contract)
            if inner is not None:
                expected = render_flags_table(live[name])
                if inner.strip() != expected.strip():
                    records.append(
                        DriftRecord(
                            SURFACE,
                            name,
                            str(docs[name]),
                            DriftKind.MISMATCH,
                            "flags block out of sync with Click",
                        )
                    )

        # Referential scan covers ALL command docs, including plugin-only ones
        # (which are excluded from `docs` above) — a dangling `brainpalace <cmd>`
        # ref is a real bug wherever it appears.
        all_docs = sorted(self.docs_dir.glob("brainpalace-*.md"))
        records.extend(referential_drift(all_docs, {c.name for c in snap.commands}))
        return records

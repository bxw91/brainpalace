"""``brainpalace init`` review screen — a two-tier resolved-config editor.

Overview screen: OFF toggleable divisions collapse to one line showing their
gate value(s); ON and pure-config (gateless) divisions list every field —
including advanced, hidden, and secrets (terminal is trusted) — under the
section intro. The user types a division number to drill in, ``A`` to edit
every division, ``C`` to accept, or ``E`` to cancel.

Drilling a division edits ALL its fields (the same set the overview shows).
The division's gate field(s) are asked first; once a gate reads OFF the
fields it governs are skipped (short-circuit). A changed field emits a
``saved →`` confirmation line. ``consent`` fields route to the caller's
``on_consent`` callback (init's existing gated/warned prompt).

The returned ``{dotpath: new_value}`` edit map is sparse (only fields whose
value the user actually changed) and is applied by init through its existing
per-block sparse writers — preserving the "write only what diverges" invariant.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

import click

from brainpalace_cli import config_fields as cf
from brainpalace_cli.prompt_render import ask_field

#: A division's gate dotpaths — fields whose "off" value collapses (part of) the
#: division. A non-gate field is shown/edited only when its governing gate is on.
#: Foundational divisions (absent here) are always-on → all fields always shown.
GROUP_GATES: dict[str, list[str]] = {
    "reranker": ["reranker.enabled"],
    "graphrag": ["graphrag.enabled"],
    "query_log": ["query_log.enabled"],
    "git_indexing": ["git_indexing.enabled"],
    "usage_metrics": ["usage_metrics.enabled"],
    # session_extraction has NO grid gate: its legacy `mode` field is grid-hidden
    # (cf.GRID_HIDDEN_FIELDS — superseded by extraction.mode), so the section always
    # shows its remaining field (quiescence_seconds), matching the dashboard.
    "extraction": ["extraction.mode"],
    # session_archiving (the free raw COPY) is its own division, gated by the
    # nested archive.enabled; the billable embed is gated by session_indexing.enabled.
    "session_archiving": ["session_indexing.archive.enabled"],
    "session_indexing": ["session_indexing.enabled"],
}

#: Per-gate "off" sentinel (default False for bool gates).
_OFF_VALUES: dict[str, Any] = {
    "extraction.mode": "off",
}

_ALL_GATES: frozenset[str] = frozenset(
    dp for paths in GROUP_GATES.values() for dp in paths
)

_CONTROL_PROMPT = "Type a number to edit · [A]ll · [C]ontinue · [E]xit"


def _divisions(layer: str | None = None) -> list[tuple[str, str]]:
    """Non-empty init divisions, in GROUP_ORDER — those with any non-hidden field.

    ``layer`` is forwarded to :func:`~brainpalace_cli.config_fields.group_fields`
    so project-only fields are hidden from the global editor and vice-versa.
    """
    out: list[tuple[str, str]] = []
    for group, label in cf.GROUP_ORDER:
        specs = cf.group_fields(group, layer=layer)
        if any(s.init_role != "hidden" for s in specs):
            out.append((group, label))
    return out


def _eff(dotpath: str, merged: dict[str, Any], edits: dict[str, Any]) -> Any:
    """Effective value: a pending grid edit wins over the resolved merged value."""
    if dotpath in edits:
        return edits[dotpath]
    val, _src = cf.resolve_value(dotpath, merged)
    return val


def _gate_on(dotpath: str, merged: dict[str, Any], edits: dict[str, Any]) -> bool:
    return bool(_eff(dotpath, merged, edits) != _OFF_VALUES.get(dotpath, False))


def _field_gate(spec: cf.FieldSpec) -> str | None:
    """The gate dotpath governing a field's visibility, or None if always visible.

    A gate field governs itself = always visible. Each gated division has a single
    gate (session_archiving → archive.enabled; session_indexing → enabled).
    """
    if spec.dotpath in _ALL_GATES:
        return None
    gates = GROUP_GATES.get(spec.group)
    return gates[0] if gates else None


def _fmt(val: Any) -> str:
    if isinstance(val, bool):
        return "on" if val else "off"
    if val in (None, ""):
        return "()"
    return str(val)


def _truncate_overview(s: str, limit: int = 70) -> str:
    """Shorten a long value for the single-line overview only (NOT when editing).
    List-like values break at the last whole element before ``limit`` and close
    with ``... ]``; other long values are cut at ``limit`` with a ``...`` marker."""
    if len(s) <= limit:
        return s
    head = s[:limit]
    comma = head.rfind(",")
    if comma > 0:
        head = head[: comma + 1]
    else:
        head = head.rstrip()
    return head + (" ... ]" if s.rstrip().endswith("]") else " ...")


def _label_with_cost(label: str, group: str) -> str:
    """Append the section's cost class to its display label, e.g.
    ``Chat Session : Vector Indexing (LLM)``. Always shown on the header so the
    billing signal survives even when the one-line description is truncated."""
    cost = cf.GROUP_COST.get(group)
    return f"{label} ({cost})" if cost else label


def _one_line_desc(desc: str, indent: int = 4) -> str:
    """Collapse a section description to a SINGLE indented line, truncated with an
    ellipsis to the terminal width. Overview only — the full text still shows when
    drilling into the division to edit."""
    s = " ".join(desc.split())
    width = shutil.get_terminal_size((80, 24)).columns
    limit = max(24, width - indent - 1)
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return " " * indent + s


def _is_empty(val: Any) -> bool:
    """Empty = None / blank str / empty dict|list|tuple. Booleans are never empty
    (they render on/off); numeric 0 is not empty."""
    if isinstance(val, bool):
        return False
    return val is None or val == "" or val in ({}, [], ())


def _visible(spec: cf.FieldSpec, merged: dict[str, Any], edits: dict[str, Any]) -> bool:
    """A field gated by ``cf.FIELD_VISIBLE_WHEN`` is shown only when its controlling
    selector holds the required value (case-insensitive, enum -> ``.value``)."""
    cond = cf.FIELD_VISIBLE_WHEN.get(spec.dotpath)
    if cond is None:
        return True
    ctrl, want = cond
    cur = _eff(ctrl, merged, edits)
    cur = getattr(cur, "value", cur)
    return str(cur).lower() == want.lower()


def render_overview(
    divisions: list[tuple[str, str]],
    merged: dict[str, Any],
    edits: dict[str, Any],
) -> None:
    """One stable overview: each division is a single line — ``N. Label : f = v |
    f = v | ...`` — listing the visible, non-empty fields (incl. secrets) of an ON
    or pure-config division, or just the gate value(s) of a collapsed OFF one.
    Empty fields and dependency-gated fields whose selector is inactive (e.g.
    ``storage.postgres`` while ``backend = chroma``) are omitted. A one-line,
    width-truncated section description (when the section has one) is printed
    under each header; the full text still shows when drilling to edit. A blank
    line separates divisions.
    """
    for i, (group, label) in enumerate(divisions, 1):
        gates = GROUP_GATES.get(group, [])
        head = f"[ {i:>2}. {_label_with_cost(label, group)} ]"
        desc = cf.GROUP_DESCRIPTIONS.get(group)
        if gates and not any(_gate_on(g, merged, edits) for g in gates):
            vals = " | ".join(_fmt(_eff(g, merged, edits)) for g in gates)
            click.echo(f"{head} {vals}")
            if desc:
                click.echo(click.style(_one_line_desc(desc), dim=True))
            click.echo("")
            continue
        parts = []
        specs = cf.group_fields(group)
        # Gate field(s) lead the line (Mode/Enabled first), matching the drill order.
        ordered = [s for s in specs if s.dotpath in gates] + [
            s for s in specs if s.dotpath not in gates
        ]
        for spec in ordered:
            if (
                spec.dotpath in cf.NESTED_MODELS
                or spec.dotpath in cf.GRID_HIDDEN_FIELDS
            ):
                continue  # container / legacy-hidden field — not shown in the grid
            gate = _field_gate(spec)
            if gate is not None and not _gate_on(gate, merged, edits):
                continue
            if not _visible(spec, merged, edits):
                continue
            val = _eff(spec.dotpath, merged, edits)
            if _is_empty(val):
                continue
            parts.append(f"{spec.prompt} = {_truncate_overview(_fmt(val))}")
        click.echo(f"{head} {' | '.join(parts)}" if parts else head)
        if desc:
            click.echo(click.style(_one_line_desc(desc), dim=True))
        click.echo("")


def _edit_division(
    group: str,
    *,
    merged: dict[str, Any],
    edits: dict[str, Any],
    on_consent: Callable[[cf.FieldSpec], None],
    layer: str | None = None,
    source_of: Callable[[str], tuple[Any, str]] | None = None,
) -> None:
    """Edit one division. Gate field(s) are asked first; once a gate reads OFF the
    fields it governs are skipped. ``hidden``/``advanced`` fields are editable here
    (what the overview shows is what you can edit); ``consent`` fields route to the
    caller's warned prompt.
    """
    label = _label_with_cost(dict(cf.GROUP_ORDER).get(group, group), group)
    click.echo("")
    click.echo(f"──── {label} " + "─" * max(0, 40 - len(label)))
    desc = cf.GROUP_DESCRIPTIONS.get(group)
    if desc:
        click.echo(f"  {desc}")

    specs = cf.group_fields(group, layer=layer)
    gates = GROUP_GATES.get(group, [])
    # Gate fields first so their freshly-edited values drive the short-circuit.
    ordered = [s for s in specs if s.dotpath in gates] + [
        s for s in specs if s.dotpath not in gates
    ]
    for spec in ordered:
        if spec.dotpath in cf.NESTED_MODELS or spec.dotpath in cf.GRID_HIDDEN_FIELDS:
            continue  # container / legacy-hidden field — not editable in the grid
        gate = _field_gate(spec)
        if gate is not None and not _gate_on(gate, merged, edits):
            continue  # owning sub-block is OFF → skip
        if not _visible(spec, merged, edits):
            continue  # dependency selector inactive (e.g. postgres while chroma)
        if spec.init_role == "consent":
            on_consent(spec)
            continue
        current = _eff(spec.dotpath, merged, edits)
        note = None
        if source_of is not None:
            _v, src = source_of(spec.dotpath)
            if src == "global":
                note = "inherited from global"
        new = ask_field(spec, default=current, inherited_note=note)
        if new != current:
            edits[spec.dotpath] = new
            click.echo(f"  saved → {spec.dotpath} = {_fmt(new)}")


def review_config(
    state_dir: str | Path,
    *,
    on_consent: Callable[[cf.FieldSpec], None],
    layer: str = "project",
    edits: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Run the review menu. Returns the sparse edit map on [C]ontinue (``{}`` if
    nothing changed) or ``None`` on [E]xit (caller cancels init).

    ``layer="project"`` reads the merged config at ``state_dir/config.yaml``
    (honors the explicit path — fixes the CWD-vs-``--path`` mismatch, finding #1).
    ``layer="global"`` reads the XDG global file only.

    Pass ``edits`` to share the accumulator with the caller's ``on_consent``
    callback (which writes consent-field choices into the SAME dict), so the live
    overview redraw and gate logic reflect consent edits immediately. The same dict
    is returned.
    """
    from brainpalace_cli.config_resolve import global_config_path, read_yaml

    source_of: Callable[[str], tuple[Any, str]] | None = None
    if layer == "global":
        merged = read_yaml(global_config_path())
    else:
        from brainpalace_server.config.provider_config import load_merged_config_dict

        # Honor the explicit state_dir (fixes the CWD-vs-path mismatch, finding #1).
        # Pass the explicit path only when the file exists — an absent file falls
        # back to auto-discovery (load_merged_config_dict raises on a missing path).
        proj_cfg = Path(state_dir) / "config.yaml"
        merged = load_merged_config_dict(proj_cfg if proj_cfg.exists() else None)
        # Build true per-field provenance (project vs global vs default) by reading
        # the two layers separately — fixes the mislabeling bug (finding #2).
        # Reuses the state_dir already passed (finding #3 — no CWD walk).
        _project_dict = read_yaml(proj_cfg)
        _global_dict = read_yaml(global_config_path())

        def source_of(
            dp: str,
            _p: dict[str, Any] = _project_dict,
            _g: dict[str, Any] = _global_dict,
        ) -> tuple[Any, str]:
            return cf.resolve_value_layered(dp, _p, _g)

    divisions = _divisions(layer)
    if edits is None:
        edits = {}

    while True:
        render_overview(divisions, merged, edits)
        choice = (
            str(click.prompt(_CONTROL_PROMPT, default="", show_default=False))
            .strip()
            .lower()
        )
        if choice == "c":
            return edits
        if choice == "e":
            return None
        if choice == "a":
            for group, _label in divisions:
                _edit_division(
                    group,
                    merged=merged,
                    edits=edits,
                    on_consent=on_consent,
                    layer=layer,
                    source_of=source_of,
                )
            continue
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(divisions):
                _edit_division(
                    divisions[idx][0],
                    merged=merged,
                    edits=edits,
                    on_consent=on_consent,
                    layer=layer,
                    source_of=source_of,
                )
        # Anything else (incl. bare Enter) re-renders the menu — never proceeds.

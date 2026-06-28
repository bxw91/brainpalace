"""Registry-driven Click prompt renderer.

Turns a :class:`brainpalace_cli.config_fields.FieldSpec` into one interactive
question: bool -> confirm; choice -> a numbered list (accept the number or the
value); int/float -> typed prompt; text -> plain prompt. ``model`` fields render
their presets as a numbered list but also accept a free-text custom value.
"""

from __future__ import annotations

from typing import Any

import click

from brainpalace_cli.config_fields import FieldSpec, options_for


def _fmt_default(val: Any) -> str:
    """Render a default value for the inherited-note bracket."""
    if val is None or val == "":
        return "()"
    return str(val)


def numbered_choice(
    label: str, options: list[str], default: Any, *, show_default: bool = True
) -> Any:
    """Render ``options`` as a numbered list; accept a 1-based number or a value.

    An unrecognized entry falls back to ``default`` (the renderer for free-text
    choices — e.g. custom models — is :func:`_free_choice`).
    """
    for i, opt in enumerate(options, 1):
        suffix = "  (default)" if opt == default else ""
        click.echo(f"  {i}. {opt}{suffix}")
    raw = str(click.prompt(label, default=default, show_default=show_default)).strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    if raw in options:
        return raw
    return default


def _free_choice(
    label: str, options: list[str], default: Any, *, show_default: bool = True
) -> Any:
    """Like :func:`numbered_choice` but a typed value that is neither a number
    nor a listed preset is accepted verbatim (custom model names)."""
    for i, opt in enumerate(options, 1):
        suffix = "  (default)" if opt == default else ""
        click.echo(f"  {i}. {opt}{suffix}")
    raw = str(click.prompt(label, default=default, show_default=show_default)).strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return raw or default


def ask_field(
    spec: FieldSpec,
    *,
    default: Any,
    inherited_note: str | None = None,
    options: list[str] | None = None,
) -> Any:
    """Ask one config field, returning the chosen value.

    ``options`` overrides the registry-derived option list (used by the wizard to
    narrow a ``model`` list to the selected provider's models).
    """
    # Blank line before every question, so successive fields are visually separated.
    click.echo("")
    if spec.help:
        click.echo(f"  {spec.help}")

    # An inherited value is shown INSIDE the prompt brackets
    # (``Provider [inherited from global: openai]:``) rather than on its own line;
    # the auto ``[default]`` is then suppressed to avoid a double bracket.
    label = (
        f"{spec.prompt} [{inherited_note}: {_fmt_default(default)}]"
        if inherited_note
        else spec.prompt
    )
    show_default = inherited_note is None

    if spec.widget == "bool":
        return click.confirm(label, default=bool(default))
    if spec.widget in ("int", "float"):
        caster = int if spec.widget == "int" else float
        if default is None:
            raw = click.prompt(label, default="", show_default=False)
            if raw in ("", None):
                return None
            try:
                return caster(raw)
            except (TypeError, ValueError):
                return None
        return click.prompt(
            label, default=default, type=caster, show_default=show_default
        )
    if spec.widget == "choice":
        opts = (
            options
            if options is not None
            else (options_for(spec.options_ref) if spec.options_ref else [])
        )
        return numbered_choice(label, opts, default, show_default=show_default)

    # text: model fields show presets but accept a free-text custom value.
    ref = spec.options_ref
    if options is not None:
        return _free_choice(label, options, default, show_default=show_default)
    if ref is not None and ref.startswith("models:"):
        return _free_choice(label, options_for(ref), default, show_default=show_default)
    # Plain text. An empty answer KEEPS the current value (including ``None``) —
    # Click rejects empty input when the default is None, so default to "" and
    # map an unchanged answer back to the original value.
    cur = "" if default is None else default
    raw = click.prompt(
        label, default=cur, show_default=default is not None and show_default
    )
    return default if raw == cur else raw

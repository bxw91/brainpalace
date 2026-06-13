"""`ai-guide` — print the canonical AI-facing BrainPalace usage guidance.

Single source of truth lives in ``brainpalace_cli/data/ai_guidance.md``; this
command renders a tier/format of it. Consumed by the SessionStart hook
(``--tier core``), read by external agents on demand (``--tier full``), and used
to generate the plugin SKILL.md (``--format skill``). See CLAUDE.md →
"AI-guidance parity".
"""

from __future__ import annotations

import click

from ..ai_guidance import render


@click.command("ai-guide")
@click.option(
    "--tier",
    type=click.Choice(["nudge", "core", "full"], case_sensitive=False),
    default="full",
    help="nudge = minimal reminder; core = decision contract; full = everything.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["markdown", "hook", "mcp", "skill"], case_sensitive=False),
    default="markdown",
    help="markdown/hook/mcp emit the tier text; skill emits the full SKILL.md.",
)
def ai_guide_command(tier: str, fmt: str) -> None:
    """Print canonical AI usage guidance (search rules, modes, gotchas).

    Examples:
      brainpalace ai-guide                      # full guidance, markdown
      brainpalace ai-guide --tier core          # the decision contract only
      brainpalace ai-guide --format skill        # regenerate SKILL.md body
    """
    text = render(tier=tier.lower(), fmt=fmt.lower())
    # `skill` output is already newline-terminated and is the canonical SKILL.md
    # artifact — emit verbatim (no extra newline) so a redirect matches the
    # generated file byte-for-byte (lint:ai-guidance-parity). Other tiers get the
    # usual trailing newline for terminal readability.
    click.echo(text, nl=(fmt.lower() != "skill"))

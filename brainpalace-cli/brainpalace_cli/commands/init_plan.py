"""Pure resolution of what `brainpalace init` should do.

Turns raw CLI inputs (explicit flags, ``--yes``, TTY presence) into a concrete
``InitPlan``. Kept free of I/O so the full decision matrix is unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class InitPlan:
    """Resolved init actions.

    start:    launch the per-project server.
    watch:    "auto" (register + index project_root, live re-index) or "off".
    sessions: index transcripts — True/False to set, None to leave untouched.
    archive:  archive transcripts — True/False to set, None to leave untouched.
    extract:  summarize sessions (distillation engine on) — True/False.
    git_history: index this repo's git commit history — True/False. Privacy-first
                 OPT-IN: default off even with --yes/TTY (commits may carry secrets).
    confirm:  an interactive confirmation is needed before executing.
    billable: the plan triggers embedding spend (doc index via watch, or sessions).
    """

    start: bool
    watch: str
    sessions: bool | None
    archive: bool | None
    extract: bool
    git_history: bool
    confirm: bool
    billable: bool


def resolve_init_plan(
    *,
    start: bool | None,
    watch: str | None,
    no_watch: bool,
    sessions: bool | None,
    archive: bool | None,
    extract: bool | None,
    git_history: bool | None,
    yes: bool,
    is_tty: bool,
) -> InitPlan:
    """Resolve raw init inputs into a concrete plan.

    Implicit "all-on" defaults (start / watch=auto / transcript index) activate
    only when the user is present to consent: an interactive TTY (gated by the
    returned ``confirm`` flag) or an explicit ``--yes``. Explicit per-capability
    flags always win, even in CI. ``archive`` defaults ON always (free backup).
    """
    active = yes or is_tty  # implicit defaults apply only with consent

    start_final = start if start is not None else active

    if not start_final:
        watch_final = "off"
    elif no_watch:
        watch_final = "off"
    elif watch is not None:
        watch_final = watch
    else:
        watch_final = "auto" if active else "off"

    if sessions is not None:
        sessions_final: bool | None = sessions
    else:
        # Embedding chat sessions is billable + sends content to a provider, so it
        # is OPT-IN: default off even with consent (set via flag or the init prompt).
        sessions_final = False

    archive_final: bool | None = archive if archive is not None else True

    extract_final = extract if extract is not None else active

    # Git-history indexing is privacy-first: commits can carry secrets, so it is
    # OPT-IN — default off even with --yes/TTY (set via flag or the init prompt).
    git_history_final = bool(git_history) if git_history is not None else False

    billable = watch_final == "auto" or bool(sessions_final)
    confirm = is_tty and not yes

    return InitPlan(
        start=start_final,
        watch=watch_final,
        sessions=sessions_final,
        archive=archive_final,
        extract=extract_final,
        git_history=git_history_final,
        confirm=confirm,
        billable=billable,
    )


def downgrade_to_config_only(plan: InitPlan) -> InitPlan:
    """Plan after the user declines the interactive confirmation.

    Drops everything that starts the server or spends money; keeps the free
    archive default so transcripts are still backed up.
    """
    return InitPlan(
        start=False,
        watch="off",
        sessions=False,
        archive=plan.archive,
        extract=False,
        git_history=False,
        confirm=False,
        billable=False,
    )


_PROVIDER_NAMES = {
    "openai": "OpenAI",
    "cohere": "Cohere",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "grok": "Grok",
}


def _trim_model_id(model: str) -> str:
    """Strip a trailing ``-YYYYMMDD`` date snapshot (e.g. claude-haiku-4-5-20251001)."""
    return re.sub(r"-\d{8}$", "", model)


def _provider_label(provider: str) -> str:
    return _PROVIDER_NAMES.get(provider, provider.title())


def _embed_tag(embedding: tuple[str, str] | None) -> str:
    if not embedding:
        return ""
    provider, model = embedding
    return f"{_provider_label(provider)} {_trim_model_id(model)}"


def _summarize_tag(summarize: tuple[str, ...] | None) -> str | None:
    """Tag for the summarize line, or None to omit the line entirely."""
    if not summarize:
        return None
    if summarize[0] == "subagent":
        return "Claude Code Haiku (subscription)"
    if summarize[0] == "provider":
        _, provider, model = summarize
        return f"{_provider_label(provider)} {_trim_model_id(model)} (API usage)"
    return None


def format_init_plan(
    plan: InitPlan,
    *,
    embedding: tuple[str, str] | None = None,
    summarize: tuple[str, ...] | None = None,
    graph_migrate: bool = False,
) -> str:
    """Multi-line, per-action preview. Data-out actions carry a ``→ <provider>`` tag.

    ``embedding`` is ``(provider, model)`` for the doc/chat embedding lines.
    ``summarize`` is ``("subagent",)`` | ``("provider", name, model)`` | ``None``
    (None ⇒ omit the summarize action entirely, e.g. the plugin is absent).
    ``graph_migrate`` adds the one-time simple→sqlite graph-store upgrade row
    (only set when re-initing an existing project still on ``simple``)."""
    emb = _embed_tag(embedding)
    summ = _summarize_tag(summarize)

    rows: list[tuple[str, str]] = []  # (action, provider tag — "" = local, no tag)
    if plan.start:
        rows.append(("start server", ""))
    if plan.watch == "auto":
        rows.append(("index docs (watch=auto)", emb))
    if plan.archive:
        rows.append(("back up chat sessions", ""))
    if plan.sessions:
        rows.append(("embed chat sessions", emb))
    if plan.extract and summ is not None:
        rows.append(("summarize chat sessions", summ))
    if plan.git_history:
        rows.append(("index git history", ""))
    if graph_migrate:
        rows.append(("upgrade graph store → sqlite", ""))
    if not rows:
        return "init will: write config only"

    width = max(len(action) for action, _ in rows)
    lines = ["init will:"]
    for action, tag in rows:
        if tag:
            lines.append(f"  · {action.ljust(width)}     → {tag}")
        else:
            lines.append(f"  · {action}")
    return "\n".join(lines)

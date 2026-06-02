"""Pure resolution of what `brainpalace init` should do.

Turns raw CLI inputs (explicit flags, ``--yes``, TTY presence) into a concrete
``InitPlan``. Kept free of I/O so the full decision matrix is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InitPlan:
    """Resolved init actions.

    start:    launch the per-project server.
    watch:    "auto" (register + index project_root, live re-index) or "off".
    sessions: index transcripts — True/False to set, None to leave untouched.
    archive:  archive transcripts — True/False to set, None to leave untouched.
    confirm:  an interactive confirmation is needed before executing.
    billable: the plan triggers embedding spend (doc index via watch, or sessions).
    """

    start: bool
    watch: str
    sessions: bool | None
    archive: bool | None
    confirm: bool
    billable: bool


def resolve_init_plan(
    *,
    start: bool | None,
    watch: str | None,
    no_watch: bool,
    sessions: bool | None,
    archive: bool | None,
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
        sessions_final = True if active else False

    archive_final: bool | None = archive if archive is not None else True

    billable = watch_final == "auto" or bool(sessions_final)
    confirm = is_tty and not yes

    return InitPlan(
        start=start_final,
        watch=watch_final,
        sessions=sessions_final,
        archive=archive_final,
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
        confirm=False,
        billable=False,
    )


def format_init_plan(plan: InitPlan) -> str:
    """One/two-line human summary of the resolved plan for the confirm prompt."""
    parts: list[str] = []
    if plan.start:
        parts.append("start server")
    if plan.watch == "auto":
        parts.append("index docs (watch=auto)")
    if plan.archive:
        parts.append("archive transcripts")
    if plan.sessions:
        parts.append("embed transcripts")
    if not parts:
        parts.append("write config only")
    line = "init will: " + " · ".join(parts)
    if plan.billable:
        bill: list[str] = []
        if plan.watch == "auto":
            bill.append("document")
        if plan.sessions:
            bill.append("transcript")
        line += "\n  → billable: " + " + ".join(bill) + " embedding"
    return line

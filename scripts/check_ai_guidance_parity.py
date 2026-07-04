#!/usr/bin/env python3
"""lint:ai-guidance-parity — keep every AI-guidance surface in sync with the
single source (`brainpalace_cli/data/ai_guidance.md`).

Fails `task before-push` when any consumer drifts from the source. Run inside the
brainpalace-cli Poetry env (it imports the live renderer):

    cd brainpalace-cli && poetry run python ../scripts/check_ai_guidance_parity.py

Checks:
  1. The plugin SKILL.md equals `ai-guide --format skill` (generated artifact —
     never hand-edit it).
  2. NUDGE and CORE tiers slice non-empty (guards the "marker token in the
     header comment" bug, which silently empties the slice).
  3. The two in-repo SessionStart hook copies are the identical thin shim and
     carry no legacy fat-hook logic (so the CLI owns all behavior).
  4. The plugin-only PreToolUse/UserPromptSubmit shims stay thin (marker
     present, no legacy logic, no direct `additionalContext` injection).
  5. `plugin.json` wires PreToolUse/SessionStart/UserPromptSubmit to their
     shims, with a survivable SessionStart timeout.
  6. MCP `Server(instructions=...)` ships the CORE tier verbatim.
  7. English-only: AI-facing guidance contains no non-ASCII *letters* (Unicode
     punctuation like — … ⊂ is fine; accented/Cyrillic letters are not).

See CLAUDE.md → "AI-guidance parity".
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the live renderer — the lint tests real code, not a stale install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brainpalace-cli"))
from brainpalace_cli.ai_guidance import core, full, nudge, render  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "brainpalace-plugin/skills/using-brainpalace/SKILL.md"
HOOK_COPIES = (
    REPO / "brainpalace-plugin/hooks/sessionstart-hook.sh",
    REPO / "brainpalace-cli/brainpalace_cli/data/hooks/sessionstart-hook.sh",
)
SHIM_MARKER = "brainpalace hook sessionstart"
LEGACY_MARKERS = ("brainpalace whoami", "<<'PY'")
# `additionalContext` is fat-hook logic the CLI must own — EXCEPT in the one
# sanctioned CLI-missing branch (an absent CLI cannot announce itself, so the
# plugin shim must). A shim carrying this marker may use `additionalContext`.
SANCTION_MARKER = "SANCTIONED-CLI-MISSING-NUDGE"

#: Plugin-only thin shims (no CLI data copy exists for these): each must exist,
#: carry its dispatch marker, and stay logic-free.
PLUGIN_SHIMS: dict[Path, str] = {
    REPO / "brainpalace-plugin/hooks/pretooluse-subagent-guard-hook.sh": (
        "brainpalace hook pretooluse"
    ),
    REPO / "brainpalace-plugin/hooks/userpromptsubmit-drain-hook.sh": (
        "brainpalace hook userpromptsubmit"
    ),
}
PLUGIN_MANIFEST = REPO / "brainpalace-plugin/.claude-plugin/plugin.json"
#: SessionStart does discovery + /health/ + an HTTP context fetch; 3s killed it
#: silently on a slow server.
MIN_SESSIONSTART_TIMEOUT = 10


def _fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def main() -> int:
    errors: list[str] = []

    # 1. SKILL.md == generated artifact.
    generated = render(tier="full", fmt="skill")
    if not SKILL.exists():
        _fail(errors, f"missing generated skill: {SKILL}")
    elif SKILL.read_text(encoding="utf-8") != generated:
        _fail(
            errors,
            f"{SKILL} is out of sync with the source. Regenerate:\n"
            "  brainpalace ai-guide --format skill > "
            "brainpalace-plugin/skills/using-brainpalace/SKILL.md",
        )

    # 2. Tier slices non-empty (header has no stray marker tokens).
    if not nudge():
        _fail(errors, "NUDGE tier is empty — check the NUDGE markers / header comment.")
    if not core():
        _fail(errors, "CORE tier is empty — check the CORE markers / header comment.")

    # 3. Hook copies are the identical thin shim, no legacy logic.
    shim_texts = []
    for hook in HOOK_COPIES:
        if not hook.exists():
            _fail(errors, f"missing hook shim: {hook}")
            continue
        text = hook.read_text(encoding="utf-8")
        shim_texts.append(text)
        if SHIM_MARKER not in text:
            _fail(errors, f"{hook} is not the thin shim (missing '{SHIM_MARKER}').")
        for legacy in LEGACY_MARKERS:
            if legacy in text:
                _fail(errors, f"{hook} still has legacy fat-hook logic ('{legacy}').")
        if "additionalContext" in text and SANCTION_MARKER not in text:
            _fail(
                errors,
                f"{hook} has fat-hook 'additionalContext' outside the sanctioned "
                f"CLI-missing branch (missing '{SANCTION_MARKER}').",
            )
    if len(shim_texts) == len(HOOK_COPIES) and len(set(shim_texts)) > 1:
        _fail(errors, "the two SessionStart hook copies differ — they must be identical.")

    # 4. Plugin-only shims are thin: marker present, no legacy logic, no
    #    injected text (only the sessionstart shim has the sanctioned branch).
    import json as _json

    for shim, marker in PLUGIN_SHIMS.items():
        if not shim.is_file():
            _fail(errors, f"missing plugin hook shim: {shim}")
            continue
        text = shim.read_text(encoding="utf-8")
        if marker not in text:
            _fail(errors, f"{shim} is not the thin shim (missing '{marker}').")
        for legacy in LEGACY_MARKERS:
            if legacy in text:
                _fail(errors, f"{shim} carries legacy fat-hook logic ('{legacy}').")
        if "additionalContext" in text:
            _fail(errors, f"{shim} injects text directly — only the CLI may.")

    # 5. plugin.json wires all three events to the shims, with a survivable
    #    SessionStart timeout.
    try:
        manifest = _json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        hooks = manifest.get("hooks", {})
        expected = {
            "PreToolUse": "pretooluse-subagent-guard-hook.sh",
            "SessionStart": "sessionstart-hook.sh",
            "UserPromptSubmit": "userpromptsubmit-drain-hook.sh",
        }
        for event, script in expected.items():
            entries = hooks.get(event) or []
            cmds = [
                h.get("command", "")
                for e in entries
                for h in e.get("hooks", [])
            ]
            if not any(script in c for c in cmds):
                _fail(errors, f"plugin.json {event} does not invoke {script}.")
            if event == "SessionStart":
                timeouts = [
                    h.get("timeout", 0)
                    for e in entries
                    for h in e.get("hooks", [])
                    if script in h.get("command", "")
                ]
                if timeouts and min(timeouts) < MIN_SESSIONSTART_TIMEOUT:
                    _fail(
                        errors,
                        "plugin.json SessionStart timeout "
                        f"{min(timeouts)}s < {MIN_SESSIONSTART_TIMEOUT}s "
                        "(kills the context fetch on a slow server).",
                    )
    except Exception as exc:  # pragma: no cover — malformed manifest
        _fail(errors, f"cannot validate plugin.json hooks: {exc}")

    # 6. MCP server ships CORE verbatim as its connect-time instructions.
    try:
        from brainpalace_cli.mcp_server import server as _mcp

        if (_mcp._INSTRUCTIONS or "") != core():
            _fail(errors, "MCP Server(instructions=...) is not the CORE tier verbatim.")
    except Exception as exc:  # noqa: BLE001
        _fail(errors, f"could not verify MCP instructions: {exc}")

    # 7. English-only: no non-ASCII letters in AI-facing guidance.
    for label, text in (("nudge", nudge()), ("full", full())):
        bad = sorted({c for c in text if ord(c) > 127 and c.isalpha()})
        if bad:
            _fail(
                errors,
                f"non-English letters in {label} guidance "
                f"(English-only rule): {bad}",
            )

    if errors:
        print("ai-guidance parity FAILED:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print(
        "ai-guidance parity OK (SKILL.md, tiers, hook shims incl. plugin-only + "
        "manifest, English-only)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

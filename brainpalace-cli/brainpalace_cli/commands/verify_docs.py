"""`verify-docs` — Layer B prose verification machinery (deterministic; no LLM).

The LLM judging itself runs **in-session** in the `doc-verifier` agent
(subscription model) — this command never calls a model. It does the
deterministic half:

  * resolve the **affected doc set** (``--all`` / ``--changed`` net-diff vs a base
    ref / explicit ``PATHS``), including the code→doc lookup via the project's own
    BrainPalace index (catches the code-moved-but-doc-didn't drift class),
  * emit a JSON **work packet** of each affected doc's *verifiable prose*
    (GENERATED blocks + frontmatter stripped — Layer A already hard-gates those)
    plus any cached verdicts the agent can reuse,
  * ingest the agent's judged verdicts (``--record``), persist them in the sidecar
    verdict cache (``scripts/doc_verify_cache.json``, mirroring the freshness
    manifest idea), print the drift report, and **re-stamp ``last_validated`` only
    for docs that came back fully clean**.

Hidden + repo-only (like ``sync-docs``): it reads the repo doc tree and the
freshness helpers under ``scripts/``. Advisory, never a hard gate — an LLM judge
is probabilistic (see the plan's "Honest limits").
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import click

# parents[3] of .../brainpalace_cli/commands/verify_docs.py == the monorepo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO_ROOT / "scripts"
#: Sidecar verdict cache: claim+grounding hash -> verdict record. Kept out of doc
#: frontmatter (same rationale as the freshness manifest) so docs render clean.
_VERDICT_CACHE = _SCRIPTS / "doc_verify_cache.json"


def _require_repo() -> None:
    """Fail clearly when run outside a BrainPalace source checkout.

    `verify-docs` is a repo-development command: it reads the freshness machinery
    and docs in `scripts/` that are NOT shipped in the installed wheel. From a
    pipx/site-packages install, `parents[3]` points into the venv, so `_SCRIPTS`
    does not exist — raise a clear error instead of a bare `FileNotFoundError` deep
    in the freshness bridge. The sources aren't installed, so failing cleanly (not
    walking for them) is the fix.
    """
    if not _SCRIPTS.is_dir():
        raise click.ClickException(
            "verify-docs is a repo-development command — run it from a BrainPalace "
            "source checkout (`poetry run …` / `task`), not an installed CLI. "
            f"Expected repo scripts at {_SCRIPTS}, which does not exist (the repo "
            "tree is not part of the installed package)."
        )


# --- freshness-machinery bridge ------------------------------------------- #
# The audited doc set, the GENERATED-block strip, the content hash, and the
# manifest live in scripts/ (shared with the doc-freshness gate). Import lazily so
# merely *registering* this command never requires the repo tree to be present.


def _freshness() -> ModuleType:
    """Import the freshness checker module from scripts/ (lazy, repo-only)."""
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    return importlib.import_module("check_doc_freshness")


def _audit_module() -> ModuleType:
    """Import add_audit_metadata from scripts/ (lazy, repo-only)."""
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    return importlib.import_module("add_audit_metadata")


def _verifiable_prose(content: str) -> str:
    """The human-owned prose a claim can be extracted from: frontmatter dropped,
    GENERATED blocks stripped (Layer A owns those facts — never re-verify them),
    line structure kept (so the agent can split sentences). This is the disjoint-
    regions contract from the plan: Layer B reads only what Layer A doesn't own."""
    fresh = _freshness()
    _, body = fresh._split_doc(content)
    return str(fresh.GENERATED_BLOCK_RE.sub("", body).strip())


def _claim_hash(claim: str, grounding: str) -> str:
    """Stable verdict-cache key = hash(normalised claim + its grounding code).

    A pure GENERATED-block regen does NOT change a claim's prose, so its key is
    stable and the cached verdict is reused; a code change that moves the
    grounding DOES change the key, forcing a re-judge of exactly that claim. The
    `doc-verifier` agent MUST compute this identically (see its agent doc).
    """

    def norm(s: str) -> str:
        return " ".join(s.split())  # collapse all whitespace runs

    return hashlib.sha256(
        (norm(claim) + "\x00" + norm(grounding)).encode("utf-8")
    ).hexdigest()


# --- affected-set resolver ------------------------------------------------- #


def _git(*args: str) -> list[str]:
    """Run a git command at the repo root, return stdout lines (empty on error)."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _changed_paths(base: str) -> list[str]:
    """Net set of changed repo-relative paths: committed since `base` PLUS the
    working tree (staged, unstaged, untracked). Computed once, on final state —
    the docs converted but not yet committed this session are included."""
    names: set[str] = set()
    names.update(_git("diff", "--name-only", f"{base}...HEAD"))
    names.update(_git("diff", "--name-only", "HEAD"))  # unstaged
    names.update(_git("diff", "--name-only", "--cached"))  # staged
    names.update(_git("ls-files", "--others", "--exclude-standard"))  # untracked
    return sorted(n for n in names if n)


#: Audited docs that are NOT subject to Layer B prose verification. A CHANGELOG is
#: a historical LOG, not documentation: its entries describe PAST behavior (often
#: naming old versions/commits), so grounding them against the CURRENT code is
#: meaningless and would yield false CONTRADICTED verdicts as the code moves on. It
#: keeps its own gate (`check_changelog_style.py`) and stays freshness-tracked —
#: only Layer B prose verification skips it.
_VERIFY_EXCLUDE: frozenset[str] = frozenset({"docs/CHANGELOG.md"})


def _audited_doc_set() -> set[str]:
    """Repo-relative paths of the docs Layer B verifies: the freshness audited set
    MINUS `_VERIFY_EXCLUDE` (historical logs that can't be grounded vs live code).
    This is the single chokepoint — resolution, code→doc mapping, and the per-diff
    marker fingerprint all derive from it, so an excluded log never enters a packet
    nor invalidates the marker when only it changed."""
    fresh = _freshness()
    files = fresh.resolve_files(str(_REPO_ROOT), fresh.DEFAULT_GLOBS)
    audited = {str(Path(f).resolve().relative_to(_REPO_ROOT)) for f in files}
    return audited - _VERIFY_EXCLUDE


def _code_to_docs(
    code_paths: list[str], audited: set[str], url: str | None, top_k: int
) -> dict[str, list[str]]:
    """Map changed code files -> audited docs that reference them, via the index.

    This is the code→prose drift catcher: a symbol moved in code, a doc still
    names the old one. Index recall, not 100% (see "Honest limits") — best-effort
    and fail-soft: if the server is down we return no code-driven docs rather than
    erroring (doc-changed docs are still verified).
    """
    import click as _click

    from ..client import ConnectionError as BPConnectionError
    from ..client import DocServeClient, ServerError
    from ..config import get_server_url

    affected: dict[str, list[str]] = {}
    if not code_paths:
        return affected
    # Fail-soft: a down/unconfigured server (get_server_url raises a ClickException,
    # query raises Connection/ServerError) yields NO code-driven docs rather than
    # aborting the sweep — doc-changed docs are still verified.
    try:
        resolved_url = url or get_server_url()
        client = DocServeClient(base_url=resolved_url)
    except (_click.ClickException, BPConnectionError, ServerError, OSError):
        return affected
    try:
        with client:
            for code in code_paths:
                stem = Path(code).stem
                resp = client.query(
                    query_text=f"{stem} {code}",
                    top_k=top_k,
                    mode="multi",
                    similarity_threshold=0.3,
                )
                for r in resp.results:
                    rel = _rel_if_audited((r.source or "").strip(), audited)
                    if rel:
                        affected.setdefault(rel, [])
                        if code not in affected[rel]:
                            affected[rel].append(code)
    except (_click.ClickException, BPConnectionError, ServerError, OSError):
        return affected  # unreachable mid-sweep — return what we have, stay soft
    return affected


def _rel_if_audited(source: str, audited: set[str]) -> str | None:
    """Normalise a query result `source` to a repo-relative audited doc path, else
    None. Sources may be absolute or repo-relative; match by suffix against the
    audited set."""
    if not source:
        return None
    if source in audited:
        return source
    try:
        rel = str(Path(source).resolve().relative_to(_REPO_ROOT))
        if rel in audited:
            return rel
    except (ValueError, OSError):
        pass
    # Suffix fallback (result paths sometimes carry an index-root prefix).
    for a in audited:
        if source.endswith(a):
            return a
    return None


def _resolve_docs(
    *,
    all_docs: bool,
    changed: bool,
    base: str,
    paths: tuple[str, ...],
    url: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Resolve the affected doc set into ordered packet entries.

    Each entry: {path, trigger, affected_by[]}. `trigger` ∈
    {all, explicit, doc-changed, code-affected}.
    """
    audited = _audited_doc_set()

    if all_docs:
        return [
            {"path": p, "trigger": "all", "affected_by": []} for p in sorted(audited)
        ]

    if paths:
        out = []
        for p in paths:
            rel = _rel_if_audited(p, audited) or p
            if rel in _VERIFY_EXCLUDE:
                continue  # never Layer-B-verify a historical log, even if named
            out.append({"path": rel, "trigger": "explicit", "affected_by": []})
        return out

    # --changed: doc-changed (direct) ∪ code-affected (index lookup).
    changed_paths = _changed_paths(base)
    doc_changed = [p for p in changed_paths if p in audited]
    code_changed = [p for p in changed_paths if p not in audited and p.endswith(".py")]
    code_map = _code_to_docs(code_changed, audited, url, top_k)

    entries: dict[str, dict[str, Any]] = {}
    for p in doc_changed:
        entries[p] = {"path": p, "trigger": "doc-changed", "affected_by": []}
    for doc, codes in code_map.items():
        if doc in entries:
            entries[doc]["affected_by"] = codes
        else:
            entries[doc] = {
                "path": doc,
                "trigger": "code-affected",
                "affected_by": codes,
            }
    return [entries[k] for k in sorted(entries)]


# --- verdict cache --------------------------------------------------------- #


def _load_cache() -> dict[str, Any]:
    try:
        with open(_VERDICT_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    with open(_VERDICT_CACHE, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(cache.items())), f, indent=2)
        f.write("\n")


# --- per-diff marker (B5, optional process gate — advisory, no model call) -- #
#: Reserved cache key recording WHICH diff was last judged. `_build_packet`'s
#: verdict filter skips it (no "doc" field), so it never leaks into a packet.
_MARKER_KEY = "__marker__"


def _relevant_changed(base: str) -> list[str]:
    """Changed paths that can move prose verification: audited docs (their prose
    changed) ∪ Python code (a moved symbol can stale a doc claim). Pure git — no
    server, no model — so the `--check` gate stays robust at before-push time."""
    audited = _audited_doc_set()
    return sorted(p for p in _changed_paths(base) if p in audited or p.endswith(".py"))


def _diff_fingerprint(base: str) -> str:
    """Coarse fingerprint of the current net diff vs `base` — the SET of
    verification-relevant changed paths (`_relevant_changed`). The marker records
    the fingerprint that was judged; `--check` fails when it no longer matches (a
    new diff needs re-judging). Process gate, never a verdict gate: it asserts
    "verify-docs was run for THIS diff", not any LLM result."""
    return hashlib.sha256(
        "\n".join(_relevant_changed(base)).encode("utf-8")
    ).hexdigest()


def _stamp_marker(base: str) -> None:
    cache = _load_cache()
    cache[_MARKER_KEY] = {"base": base, "fingerprint": _diff_fingerprint(base)}
    _save_cache(cache)


#: Per-machine weekly-sweep cadence file (gitignored). The SessionStart reminder
#: hook (.claude/hooks/sessionstart-docverify-sweep.sh) reads it; ANY verify run
#: stamps `last_verify` here to reset the weekly reminder clock.
_SWEEP_STATE = _REPO_ROOT / ".claude" / ".doc-verify-sweep.json"


def _stamp_weekly_clock() -> None:
    """Record that a verification ran today, resetting the weekly-sweep reminder.
    Fail-soft: cadence bookkeeping must never break a `--record`."""
    from datetime import date

    try:
        state: dict[str, Any] = {}
        if _SWEEP_STATE.exists():
            loaded = json.loads(_SWEEP_STATE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        state["last_verify"] = date.today().isoformat()
        _SWEEP_STATE.parent.mkdir(parents=True, exist_ok=True)
        _SWEEP_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


# --- packet emit ----------------------------------------------------------- #


def _build_packet(entries: list[dict[str, Any]], base: str) -> dict[str, Any]:
    """Assemble the work packet the agent judges: per doc, the verifiable prose +
    any cached verdicts (so the agent self-skips unchanged claim+grounding pairs)."""
    cache = _load_cache()
    docs = []
    for e in entries:
        rel = e["path"]
        full = _REPO_ROOT / rel
        try:
            content = full.read_text(encoding="utf-8")
        except OSError:
            continue
        cached = [
            {"hash": h, "claim": rec.get("claim"), "verdict": rec.get("verdict")}
            for h, rec in cache.items()
            if rec.get("doc") == rel
        ]
        docs.append(
            {
                "path": rel,
                "trigger": e["trigger"],
                "affected_by": e.get("affected_by", []),
                "prose": _verifiable_prose(content),
                "cached_verdicts": cached,
            }
        )
    return {
        "base": base,
        "claim_hash": "sha256(normalise(claim) + 0x00 + normalise(grounding))",
        "docs": docs,
    }


# --- record verdicts + re-stamp clean -------------------------------------- #

_VERDICTS = ("SUPPORTED", "CONTRADICTED", "UNVERIFIABLE")


def _record_verdicts(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist judged verdicts to the cache; re-stamp fully-clean docs.

    A doc is **clean** iff every submitted verdict for it is SUPPORTED (no
    CONTRADICTED, no UNVERIFIABLE). Only clean docs get re-stamped (last_validated
    + freshness manifest hash). Returns a per-doc summary for the drift report.
    """
    verdicts = payload.get("verdicts") or []
    cache = _load_cache()
    per_doc: dict[str, dict[str, list[Any]]] = {}

    for v in verdicts:
        doc = v.get("doc")
        claim = v.get("claim", "")
        grounding = v.get("grounding", "")
        verdict = (v.get("verdict") or "").upper()
        if not doc or verdict not in _VERDICTS:
            continue
        h = _claim_hash(claim, grounding)
        cache[h] = {
            "doc": doc,
            "claim": claim,
            "grounding": grounding,
            "verdict": verdict,
            "evidence": v.get("evidence", ""),
        }
        slot = per_doc.setdefault(
            doc, {"SUPPORTED": [], "CONTRADICTED": [], "UNVERIFIABLE": []}
        )
        slot[verdict].append({"claim": claim, "evidence": v.get("evidence", "")})

    _save_cache(cache)

    clean_docs = [
        doc
        for doc, s in per_doc.items()
        if not s["CONTRADICTED"] and not s["UNVERIFIABLE"]
    ]
    restamped = _restamp(clean_docs) if clean_docs else []
    return {"per_doc": per_doc, "clean": clean_docs, "restamped": restamped}


def _restamp(docs: list[str]) -> list[str]:
    """Re-stamp last_validated + manifest hash for specific clean docs only."""
    from datetime import date

    fresh = _freshness()
    audit = _audit_module()
    manifest = fresh.load_manifest()
    today = date.today().isoformat()
    done = []
    for rel in docs:
        full = _REPO_ROOT / rel
        try:
            content = full.read_text(encoding="utf-8")
        except OSError:
            continue
        new_content, _action = audit.update_frontmatter(content, today)
        if new_content != content:
            full.write_text(new_content, encoding="utf-8")
        manifest[rel] = fresh.content_hash(new_content)
        done.append(rel)
    fresh.save_manifest(manifest)
    return done


def _render_report(summary: dict[str, Any]) -> str:
    """Human drift report: the CONTRADICTED + UNVERIFIABLE list, per doc."""
    per_doc = summary["per_doc"]
    lines: list[str] = []
    drift = 0
    for doc in sorted(per_doc):
        s = per_doc[doc]
        problems = s["CONTRADICTED"] + s["UNVERIFIABLE"]
        if not problems:
            continue
        lines.append(f"\n{doc}")
        for item in s["CONTRADICTED"]:
            drift += 1
            lines.append(f"  [CONTRADICTED] {item['claim']}")
            if item["evidence"]:
                lines.append(f"      evidence: {item['evidence']}")
        for item in s["UNVERIFIABLE"]:
            drift += 1
            lines.append(f"  [UNVERIFIABLE] {item['claim']}")
    n_docs = sum(
        1 for d in per_doc if per_doc[d]["CONTRADICTED"] or per_doc[d]["UNVERIFIABLE"]
    )
    head = f"Doc verification: {drift} drift item(s) across {n_docs} doc(s)."
    if summary["restamped"]:
        head += f"\nRe-stamped {len(summary['restamped'])} clean doc(s): " + ", ".join(
            summary["restamped"]
        )
    if drift == 0:
        head += "\nNo drift. (Advisory: LLM judge is probabilistic.)"
    return head + ("\n" + "\n".join(lines) if lines else "")


# --- command --------------------------------------------------------------- #


@click.command("verify-docs", hidden=True)
@click.argument("paths", nargs=-1)
@click.option(
    "--all",
    "all_docs",
    is_flag=True,
    help=(
        "Whole audited doc set (heavy full baseline — prefer per-path/--changed "
        "and walk in batches; the verdict cache accumulates across runs)."
    ),
)
@click.option(
    "--changed",
    is_flag=True,
    help="Verify the net-diff affected set (done-boundary).",
)
@click.option(
    "--base", default="main", help="Base ref for --changed net diff (default: main)."
)
@click.option(
    "--record",
    "record_file",
    default=None,
    help="Ingest judged verdicts (JSON file, or '-' for stdin).",
)
@click.option(
    "--check",
    "check_marker",
    is_flag=True,
    help="Process gate (no LLM): exit non-zero if the current diff was not verified.",
)
@click.option(
    "--url",
    envvar="BRAINPALACE_URL",
    default=None,
    help="Server URL for the code→doc lookup.",
)
@click.option(
    "-k",
    "--top-k",
    default=8,
    type=int,
    help="Top-k for the code→doc lookup (default: 8).",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit the JSON work packet (default on resolve).",
)
def verify_docs_command(
    paths: tuple[str, ...],
    all_docs: bool,
    changed: bool,
    base: str,
    record_file: str | None,
    check_marker: bool,
    url: str | None,
    top_k: int,
    json_output: bool,
) -> None:
    """Advisory prose-drift verification (deterministic half; agent judges).

    \b
    Resolve a work packet (default). Go INCREMENTALLY — judging burns subscription
    limits, so verify a small bounded batch per run; the verdict cache accumulates:
      brainpalace verify-docs docs/USER_GUIDE.md    # one doc — the normal case
      brainpalace verify-docs --changed             # done-boundary (net diff vs main)
      brainpalace verify-docs --all                 # FULL baseline — heavy; batch it
    emits {base, claim_hash, docs:[{path,trigger,affected_by,prose,cached_verdicts}]}.

    \b
    Record judged verdicts (the agent pipes them back):
      brainpalace verify-docs --record verdicts.json
      brainpalace verify-docs --record -            # stdin
    payload {verdicts:[{doc,claim,grounding,verdict,evidence}]},
    verdict ∈ SUPPORTED|CONTRADICTED|UNVERIFIABLE. Clean docs (all SUPPORTED) are
    re-stamped; the drift report (CONTRADICTED + UNVERIFIABLE) is printed.
    """
    _require_repo()
    if check_marker:
        # B5 process gate (advisory, opt-in for pre-push wiring): did verify-docs
        # run for THIS diff? Compares the current net-diff fingerprint to the one
        # the last --record stamped. Never asserts an LLM verdict.
        relevant = _relevant_changed(base)
        if not relevant:
            click.echo("verify-docs: no doc/code changes vs base — nothing to verify.")
            return
        marker = _load_cache().get(_MARKER_KEY) or {}
        if marker.get("fingerprint") == _diff_fingerprint(base):
            click.echo("verify-docs: current diff already verified (marker matches).")
            return
        raise SystemExit(
            "verify-docs: current diff NOT verified (Layer B prose check).\n"
            "Run the doc-verifier — in Claude Code: `/brainpalace-verify-docs "
            "--changed` (or dispatch the doc-verifier agent) — it judges the "
            "affected docs and records the per-diff marker. Then re-run this gate.\n"
            f"Affected by changes to: {', '.join(relevant[:8])}"
            + (" …" if len(relevant) > 8 else "")
        )

    if record_file is not None:
        raw = (
            sys.stdin.read()
            if record_file == "-"
            else Path(record_file).read_text(encoding="utf-8")
        )
        try:
            payload = json.loads(raw)
        except ValueError as e:
            raise SystemExit(f"verify-docs --record: invalid JSON ({e})") from e
        summary = _record_verdicts(payload)
        # Stamp the per-diff marker so `--check` can later confirm THIS diff was
        # judged (skip for whole-set sweeps — there is no diff to fingerprint).
        if not all_docs:
            _stamp_marker(base)
        # Any verify run (diff or full sweep) resets the weekly-sweep reminder.
        _stamp_weekly_clock()
        if json_output:
            click.echo(json.dumps(summary, indent=2))
        else:
            click.echo(_render_report(summary))
        return

    if not (all_docs or changed or paths):
        raise SystemExit(
            "verify-docs: pass --all, --changed, PATHS, or --record. See --help."
        )

    entries = _resolve_docs(
        all_docs=all_docs, changed=changed, base=base, paths=paths, url=url, top_k=top_k
    )
    # The packet IS the machine contract the agent consumes — always JSON on
    # resolve (`--json` is accepted for symmetry/explicitness but is the default).
    packet = _build_packet(entries, base if changed else "-")
    click.echo(json.dumps(packet, indent=2))

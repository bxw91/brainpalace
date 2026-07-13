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
import io
import json
import os
import subprocess
import sys
import tempfile
import tokenize
from datetime import date
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
#: Durable human-confirm ledger: a claim+grounding hash the human has explicitly
#: vouched for. Keyed identically to the verdict cache (`_claim_hash`), each row is
#: ``{doc, claim, grounding, confirmed_by, confirmed_at}``. THIS is the persistent
#: record of a "mark verified by human" order — the order is captured the instant it
#: is given, and every later sweep consults it (see `_derive_record`), so the verdict
#: survives even if no `--record` sweep runs that session. It is SEPARATE from the
#: rewritten verdict cache precisely so a re-record can never erase a standing order.
#: Scope (by design): only an `unresolved` claim (no code path, no audited-doc dep) is
#: confirmable — code is still the sole ground truth, so a code-tier claim must be
#: re-prosed to drop its code referent before it can be human-vouched.
_CONFIRMED_LEDGER = _SCRIPTS / "doc_verify_confirmed.json"


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


# --- durable human-confirm ledger ------------------------------------------ #


def _load_confirmed() -> dict[str, Any]:
    """The durable human-confirm ledger (claim-hash -> order row), or ``{}`` when no
    order has ever been given. Read on every record/resettle so a standing order is
    re-applied without a fresh sweep input. A corrupt ledger is treated as empty
    (fail-soft): a missing order only means a claim re-surfaces as UNVERIFIABLE, never
    a wrong SUPPORTED, so it must never abort a verification run."""
    try:
        data = json.loads(_CONFIRMED_LEDGER.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_confirmed(ledger: dict[str, Any]) -> None:
    """Persist the human-confirm ledger atomically (temp + replace), sorted for a
    stable, review-friendly diff — it is a checked-in file."""
    _CONFIRMED_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIRMED_LEDGER.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(_CONFIRMED_LEDGER)


def _claim_confirmed(claim_hash: str) -> bool:
    """True iff this exact claim+grounding has a standing human-confirm order. This is
    the second human-vouch signal alongside `_doc_audit_fresh` — but per-CLAIM and
    durable, so the order is honoured the instant it is recorded and across every
    later sweep, independent of the host doc's manifest re-stamp timing."""
    return claim_hash in _load_confirmed()


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


def _default_base() -> str:
    """Base ref for the `--changed` / `--check` net diff. `main` (the historical
    Click default) is WRONG for this repo: `stable` (the working branch) and
    `main` (the squashed publish mirror) have UNRELATED histories, so `main...HEAD`
    is empty and the affected set collapses to nothing — the `--check` gate then
    trivially passes and prose drift builds up unseen.

    The real done-boundary is the PREVIOUS release: the most recent `release:`
    commit reachable from HEAD. `before-push` runs at RELEASING step 8, before the
    new release commit is made at step 9, so this always resolves to the prior
    release — i.e. exactly the changes THIS release ships. Falls back to `main`
    when no release commit exists (a fresh repo / non-release history)."""
    rel = _git("log", "-E", "--grep=^release:", "--format=%H", "-1")
    return rel[0] if rel else "main"


#: Docs that are NEITHER verified by Layer B NOR usable as grounding for another
#: doc's claim — historical / frozen / scratch material that describes PAST or
#: INTENDED state, so grounding live code against it is meaningless (false verdicts
#: as the code moves on). Two shapes:
#:   * exact files — CHANGELOG (a historical log; keeps its own `check_changelog_
#:     style.py` gate) and ORIGINAL_SPEC (the frozen Phase-1 design intent).
#:   * path prefixes — `docs/superpowers/` (past plan/spec artifacts) and
#:     `.planning/` (local, gitignored scratch). Whole trees, so a prefix, not a
#:     file list.
#: This is belt-and-suspenders with `_grounding_tier`'s fail-closed default (an
#: unrecognized `.md` never grounds anyway), but naming them makes the verdict tier
#: explicit (`excluded-doc`) instead of generic, and keeps them out of the audited
#: set even if a future DEFAULT_GLOBS change would pull them in.
_EXCLUDE_FILES: frozenset[str] = frozenset(
    {"docs/CHANGELOG.md", "docs/ORIGINAL_SPEC.md"}
)
_EXCLUDE_PREFIXES: tuple[str, ...] = ("docs/superpowers/", ".planning/")


def _is_excluded(rel: str) -> bool:
    """True if a repo-relative path is excluded from BOTH verification and use as a
    grounding source (historical/frozen/scratch — see `_EXCLUDE_FILES`/PREFIXES)."""
    return rel in _EXCLUDE_FILES or rel.startswith(_EXCLUDE_PREFIXES)


def _audited_doc_set() -> set[str]:
    """Repo-relative paths of the docs Layer B verifies: the freshness audited set
    MINUS everything `_is_excluded` (historical logs / frozen specs / planning
    scratch that can't be grounded vs live code). This is the single chokepoint —
    resolution, code→doc mapping, and the per-diff marker fingerprint all derive
    from it, so an excluded doc never enters a packet nor invalidates the marker."""
    fresh = _freshness()
    files = fresh.resolve_files(str(_REPO_ROOT), fresh.DEFAULT_GLOBS)
    audited = {str(Path(f).resolve().relative_to(_REPO_ROOT)) for f in files}
    return {d for d in audited if not _is_excluded(d)}


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


def _server_reachable(url: str | None) -> bool:
    """True if the index server answers a health check. Used to gate a sweep:
    grounding every claim needs the server, so we must not hand the agent a packet
    it can't judge (a down server would otherwise yield false UNVERIFIABLE)."""
    import click as _click

    from ..client import ConnectionError as BPConnectionError
    from ..client import DocServeClient, ServerError
    from ..config import get_server_url

    try:
        resolved = url or get_server_url()
        with DocServeClient(base_url=resolved) as client:
            client.health()
        return True
    except (_click.ClickException, BPConnectionError, ServerError, OSError):
        return False


def _ensure_server_up(url: str | None) -> bool:
    """Confirm the index server answers; if not, attempt ONE restart
    (`brainpalace start`) and poll health briefly. Returns True if up (already or
    after restart), False if it stays unreachable. Verification must STOP rather
    than ground against a dead server — a crash mid-sweep would otherwise record
    false UNVERIFIABLE verdicts for claims it simply couldn't check."""
    import time

    if _server_reachable(url):
        return True
    # Try to (re)start it with the SAME interpreter running this command (the source
    # checkout), so we don't depend on a possibly-stale `brainpalace` on PATH.
    try:
        subprocess.run(
            [sys.executable, "-m", "brainpalace_cli", "start"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    for _ in range(10):  # poll up to ~10s for it to come up
        if _server_reachable(url):
            return True
        time.sleep(1)
    return False


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
            if _is_excluded(rel):
                continue  # never Layer-B-verify excluded material, even if named
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


# --- recently-verified skip (relation-driven; no time window) ---------------- #


def _prose_verified_docs() -> set[str]:
    """Repo-relative paths that have ≥1 prose verdict in the verdict cache — i.e.
    docs the Layer-B prose verifier has actually judged.

    This is the **provenance signal** relation-driven skip relies on.
    `last_validated` alone is ambiguous: it is written by BOTH
    `add_audit_metadata.py` (the human "confirmed
    accurate" audit / doc-freshness gate) AND `verify-docs --record` (this prose
    verifier). A doc the human audited but the prose verifier never judged would
    otherwise look "fresh" and be silently dropped from a sweep. Cache entries are
    written ONLY by `_record_verdicts`, so presence here proves prose was judged.
    """
    verified: set[str] = set()
    for h, rec in _load_cache().items():
        if h == _MARKER_KEY or not isinstance(rec, dict):
            continue
        doc = rec.get("doc")
        if isinstance(doc, str) and doc:
            verified.add(doc)
    return verified


def _filter_fresh(
    entries: list[dict[str, Any]], force: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split resolved entries into (kept, skipped). A doc is **skipped** only when
    ALL hold (there is NO time window — a stamp's age is irrelevant):

      * it has been **prose-verified** (≥1 verdict in the cache), AND
      * its authored prose is **unchanged** (manifest-hash match), AND
      * it is **fully clean** (every recorded verdict SUPPORTED — code-grounded),
        AND
      * **every grounded relation is unchanged** — for each of the doc's verdict
        records, its `grounding_files`/dirs still hash to the stored value
        (`_relation_unchanged`).

    Any doc with edited prose, a moved/added/removed grounded file or dir member, a
    missing relation, an open verdict, or no prose verdict at all is kept (re-
    verified). `force=True` skips nothing — the manual full re-verify
    (`--all --force`). Pure filesystem: no index server needed."""
    fresh = _freshness()
    manifest = fresh.load_manifest()
    verified = _prose_verified_docs()
    cache = _load_cache()
    clean = _clean_verified_docs(cache)
    kept: list[dict[str, Any]] = []
    skipped: list[str] = []
    for e in entries:
        rel = e["path"]
        if force:
            kept.append(e)
            continue
        full = _REPO_ROOT / rel
        try:
            content = full.read_text(encoding="utf-8")
        except OSError:
            kept.append(e)
            continue
        prose_verified = rel in verified
        unchanged = manifest.get(rel) == fresh.content_hash(content)
        is_clean = rel in clean
        relations_ok = all(
            _relation_unchanged(rec)
            for h, rec in cache.items()
            if h != _MARKER_KEY and isinstance(rec, dict) and rec.get("doc") == rel
        )
        if prose_verified and unchanged and is_clean and relations_ok:
            skipped.append(rel)
        else:
            kept.append(e)
    return kept, skipped


# --- verdict cache --------------------------------------------------------- #


def _load_cache() -> dict[str, Any]:
    """Load the verdict cache. A MISSING file is an empty cache (fine). A present
    but **corrupt** file is NOT silently treated as empty — that would wipe every
    recorded verdict and the audit trail on the next save. Instead we move the
    corrupt file aside and abort loudly, so a human notices and restores it."""
    if not _VERDICT_CACHE.exists():
        return {}
    try:
        with open(_VERDICT_CACHE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        backup = _VERDICT_CACHE.with_suffix(".corrupt")
        try:
            _VERDICT_CACHE.replace(backup)
        except OSError:
            pass
        raise SystemExit(
            f"verify-docs: verdict cache is corrupt ({e}); moved to {backup}. "
            "Aborting rather than silently discarding all recorded verdicts — "
            "restore it from git (scripts/doc_verify_cache.json) and retry."
        ) from e
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict[str, Any]) -> None:
    """Atomically persist the cache: write a temp file in the same dir, then
    `os.replace` it into place. A crash mid-write leaves the old cache intact
    instead of a truncated/corrupt file."""
    _VERDICT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(_VERDICT_CACHE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(cache.items())), f, indent=2)
            f.write("\n")
        os.replace(tmp, _VERDICT_CACHE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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

#: Human-decision report (repo-dev scope). Written ONLY when verification is genuinely
#: stuck — every audited doc judged once AND a set of doc-dep claims can never reach
#: code (a dependency cycle or an orphan with no code exit). Deleted when no such set
#: remains. Its existence means "a human must break a cycle or ground a claim on code."
#: NOT under docs/ — never an audited doc.
_NEEDS_HUMAN_REPORT = _REPO_ROOT / ".claude" / "doc-verify-needs-human.md"


def _read_sweep_state() -> dict[str, Any]:
    """Load the sweep-state JSON, or {} if absent/unreadable. Fail-soft."""
    try:
        if _SWEEP_STATE.exists():
            loaded = json.loads(_SWEEP_STATE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
    except Exception:
        pass
    return {}


def _write_sweep_state(state: dict[str, Any]) -> None:
    _SWEEP_STATE.parent.mkdir(parents=True, exist_ok=True)
    _SWEEP_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _stamp_weekly_clock() -> None:
    """Record that a verification ran today, resetting the weekly-sweep reminder.
    Fail-soft: cadence bookkeeping must never break a `--record`."""
    try:
        state = _read_sweep_state()
        state["last_verify"] = date.today().isoformat()
        _write_sweep_state(state)
    except Exception:
        pass


# --- packet emit ----------------------------------------------------------- #


def _raw(rec: dict[str, Any]) -> str:
    """A record's RAW verdict (the agent's judgment): `raw_verdict` if present, else
    `verdict` (records written before the doc-dep split carry only `verdict`)."""
    return (rec.get("raw_verdict") or rec.get("verdict") or "").upper()


def _build_packet(entries: list[dict[str, Any]], base: str) -> dict[str, Any]:
    """Assemble the work packet the agent judges: per doc, the verifiable prose +
    any **terminal** cached verdicts (so the agent self-skips unchanged claim pairs).

    Reuse keys on the claim's **raw** verdict (`_raw`): only a raw SUPPORTED or
    CONTRADICTED is fed back (so a doc-dep settled to PENDING is reused via its raw
    SUPPORTED and the agent echoes it verbatim). A raw UNVERIFIABLE claim is omitted so
    the agent re-grounds it — the index may now return code. This is the "only re-check
    the leftover claims" contract: clean claims cost nothing, the open subset retries.

    Each cached verdict now carries ``fresh: bool`` (relation unchanged) so the agent
    re-grounds only stale or new claims. A cached verdict is reusable only when
    ``fresh`` is true (its grounded files/dirs are unchanged) AND its claim is still
    present in the prose; re-emit a fresh reused verdict verbatim into ``--record``
    (no re-grounding, no re-judging); a ``fresh: false`` entry must be re-grounded
    and re-judged."""
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
            {
                "hash": h,
                "claim": rec.get("claim"),
                "grounding": rec.get("grounding", ""),
                "grounding_files": rec.get("grounding_files", []),
                "verdict": _raw(rec),
                "fresh": _relation_unchanged(rec),
            }
            for h, rec in cache.items()
            if isinstance(rec, dict)
            and rec.get("doc") == rel
            and _raw(rec) in _TERMINAL_VERDICTS
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

#: A claim's recorded STATUS (orthogonal to its SOURCE, which is `grounding_tier`).
#: PENDING is non-terminal: a doc-dep claim whose dependency is not yet clean — the
#: settle (not the agent) assigns it and may promote it to SUPPORTED once every
#: dependency clears, or to UNVERIFIABLE if it can never reach code. SUPPORTED/
#: CONTRADICTED are terminal (reused from cache); UNVERIFIABLE is terminal-for-now (no
#: source vouches — needs code/human). A human-asserted external fact is NOT a separate
#: status: it is recorded SUPPORTED with `grounding_tier="audit"` (see `_grounding_tier`
#: / `_doc_audit_fresh`) — the source tier holds the provenance, status stays SUPPORTED.
_VERDICTS = ("SUPPORTED", "CONTRADICTED", "UNVERIFIABLE", "PENDING")

#: Verdicts safe to REUSE from the cache without re-judging. Only the terminal ones:
#: a PENDING/UNVERIFIABLE outcome is re-derived by the settle, not the agent. The
#: packet feeds a doc-dep claim's RAW verdict, so reuse keys on `_raw(rec)`.
_TERMINAL_VERDICTS = frozenset({"SUPPORTED", "CONTRADICTED"})

#: Verdicts that mean a doc is NOT clean (blocks the re-stamp / cannot launder onward).
#: PENDING joins them — a doc waiting on an unclean dependency must not count as clean —
#: but PENDING is NEVER surfaced to a human (see _render_report). SUPPORTED is the only
#: clean status (whether code-confirmed or audit-tier human-vouched).
_OPEN_VERDICTS = frozenset({"CONTRADICTED", "UNVERIFIABLE", "PENDING"})


def _docs_with_verdicts(cache: dict[str, Any]) -> set[str]:
    """Every doc with ≥1 recorded verdict (judged at least once)."""
    out: set[str] = set()
    for h, rec in cache.items():
        if h == _MARKER_KEY or not isinstance(rec, dict):
            continue
        doc = rec.get("doc")
        if isinstance(doc, str) and doc:
            out.add(doc)
    return out


def _clean_verified_docs(cache: dict[str, Any]) -> set[str]:
    """Repo-relative paths of docs that are FULLY clean in the cache — every recorded
    verdict SUPPORTED, none CONTRADICTED/UNVERIFIABLE/PENDING. These are the only docs
    that may serve as trustworthy grounding for *another* doc's claim: their own claims
    have been confirmed against code (transitively) or, for `audit`-tier claims, are
    human-asserted externals vouched by the audit stamp. A doc with ≥1 verdict but any
    open verdict is NOT clean, so it can't launder onward."""
    seen: dict[str, set[str]] = {}
    for h, rec in cache.items():
        if h == _MARKER_KEY or not isinstance(rec, dict):
            continue
        doc = rec.get("doc")
        if isinstance(doc, str) and doc:
            seen.setdefault(doc, set()).add((rec.get("verdict") or "").upper())
    return {d for d, vs in seen.items() if vs and not (vs & _OPEN_VERDICTS)}


def _verification_stats(cache: dict[str, Any], audited: set[str]) -> dict[str, int]:
    """Snapshot of verification progress across the project-doc set:
      * ``total``   — audited project docs,
      * ``full``    — fully verified (every claim SUPPORTED — code or audit tier;
                      re-stamped),
      * ``partial`` — judged but with ≥1 open item (CONTRADICTED/UNVERIFIABLE/
                      PENDING) — i.e. seen but not clean,
      * ``none``    — never prose-judged (no verdict in the cache).
    Cache rows for docs no longer audited (renamed/removed) are ignored by
    intersecting with the live audited set, so the counts always sum to `total`."""
    clean = _clean_verified_docs(cache) & audited
    judged = _docs_with_verdicts(cache) & audited
    return {
        "total": len(audited),
        "full": len(clean),
        "partial": len(judged - clean),
        "none": len(audited - judged),
    }


def _render_stats(stats: dict[str, int]) -> str:
    """One-line progress banner for the start of a verification round."""
    return (
        f"verify-docs: {stats['total']} project docs — "
        f"{stats['full']} fully verified, "
        f"{stats['partial']} partial, "
        f"{stats['none']} not verified."
    )


def _render_packet_count(n: int) -> str:
    """Actionable count for THIS round: docs still queued to re-judge. Distinct from
    `_render_stats`' cache status ("N not verified" = never recorded a verdict): a
    fully-verified doc can still be queued here because a file it grounds on changed
    since. Printed next to the packet so a reader never reads "0 not verified" as
    "nothing to do" and overlooks the queue below."""
    return f"verify-docs: {n} doc(s) to re-judge this round" + (
        " — verification converged, nothing queued." if n == 0 else "."
    )


def _order_by_cost(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the packet **smallest verifiable-prose first**. Two wins at once:

      * **Pacing** — judging cost scales with the prose (claims are extracted from
        it), so cheap docs go first: a budget-capped batch clears MORE docs and
        never blows the cap mid-doc.
      * **Rough dependency order, free** — large docs are the hubs (README,
        ARCHITECTURE, USER_GUIDE) that reference many others; small docs are mostly
        leaves grounding on code. So smallest-first ≈ leaves-first (~0.6 correlation
        with out-degree here), building the verified base that unblocks dependents
        without any graph machinery. The defer scheduler covers the cases this
        misorders, and those are the cheapest (small) docs to re-judge.

    Sort by `len(verifiable_prose)`; unreadable docs sort last (skipped downstream),
    `path` breaks ties for determinism."""

    def key(e: dict[str, Any]) -> tuple[int, int, str]:
        try:
            content = (_REPO_ROOT / e["path"]).read_text(encoding="utf-8")
        except OSError:
            return (1, 0, e["path"])
        return (0, len(_verifiable_prose(content)), e["path"])

    return sorted(entries, key=key)


def _filter_unclassified(
    entries: list[dict[str, Any]], manifest: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Classify-or-refuse gate for NEW doc surfaces. The audited globs are an
    allowlist, but a file can still land inside a tracked dir (a plugin dropping a
    plan file in `agents/`, a widened glob). Such a file is glob-matched yet absent
    from the freshness manifest — indistinguishable, automatically, from a genuinely
    new doc awaiting its first verification. So we don't guess: an unclassified doc
    is **dropped from auto-sweeps** (`--all`/`--changed`) and surfaced, but is
    verifiable the moment it is **named explicitly** — naming it IS the human
    classification "yes, this is a real doc." Scratch never gets named, so it is
    never auto-verified; the warning tells the human to verify it (real) or exclude
    it (scratch). A doc already in the manifest is classified — kept."""
    kept: list[dict[str, Any]] = []
    unclassified: list[str] = []
    for e in entries:
        if e.get("trigger") == "explicit" or e["path"] in manifest:
            kept.append(e)
        else:
            unclassified.append(e["path"])
    return kept, unclassified


def _refresh_needs_human_report(cache: dict[str, Any], stuck: list[str]) -> list[str]:
    """Write the human-decision report iff verification is genuinely stuck — every
    audited doc judged at least once AND `stuck` (settle's no-path-to-code set) is
    non-empty. While any audited doc is unjudged, draining it may break a cycle, so
    don't cry stuck — and delete any stale report. Returns the reported paths."""
    audited = _audited_doc_set()
    judged = _docs_with_verdicts(cache)
    unjudged = {d for d in audited if d not in judged and not _is_excluded(d)}
    if unjudged or not stuck:
        if _NEEDS_HUMAN_REPORT.exists():
            _NEEDS_HUMAN_REPORT.unlink()
        return []
    _write_needs_human_report(cache, stuck)
    return sorted(stuck)


def _write_needs_human_report(cache: dict[str, Any], stuck: list[str]) -> None:
    """Render the human-decision report: each stuck doc and its settled-UNVERIFIABLE
    doc-dep claims with the dependency they can never reach."""
    dead = set(stuck)
    lines = [
        "# Doc verification — needs human decision",
        "",
        f"Generated {date.today().isoformat()}. Every audited doc has been judged, "
        "but the doc-dep claims below can never reach code — a dependency cycle, or "
        "a dependency with no path to a code-grounded doc. The verifier holds them "
        "at UNVERIFIABLE until a human acts: ground one claim on code, rewrite it to "
        "cite a code-grounded doc, or accept it.",
        "",
    ]
    for doc in sorted(dead):
        lines.append(f"## {doc}")
        for h, rec in cache.items():
            if h == _MARKER_KEY or not isinstance(rec, dict):
                continue
            if (
                rec.get("doc") == doc
                and rec.get("grounding_tier") == "doc-dep"
                and (rec.get("verdict") or "").upper() == "UNVERIFIABLE"
            ):
                deps = ", ".join(rec.get("grounding_files") or []) or "(unverified doc)"
                lines.append(f"  - claim: {rec.get('claim', '')}")
                lines.append(f"    depends on (no path to code): {deps}")
        lines.append("")
    _NEEDS_HUMAN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    _NEEDS_HUMAN_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _grounding_tier(
    grounding: str, audited: set[str], clean_verified: set[str], doc: str | None = None
) -> str:
    """Classify a claim's grounding by source-of-truth strength. **Fails CLOSED.**

      * ``code``      — a real non-doc source path (``*.py``, tests, config). Code is
                        the ground truth; the only tier that confirms directly.
      * ``doc-dep``   — no code path, but ≥1 **audited** doc token *other than the host
                        doc* (``doc``): the claim depends on another doc the verifier
                        judges and that *can* become clean. A grounding naming ONLY the
                        host doc itself (self-reference) is NOT a dependency (a doc
                        can't ground its own claim) so it falls to ``unresolved``
                        (like `_doc_paths_from_grounding`, which drops self-refs).
                        Confirmation is deferred to the settle (SUPPORTED/PENDING/
                        UNVERIFIABLE), never decided here.
      * ``unresolved``— an **excluded** doc (CHANGELOG / superpowers / ``.planning``) or
                        an unrecognized ``.md`` (never verified → never clean), OR no
                        usable path token. At record time `_record_verdicts` may UPGRADE
                        an ``unresolved`` claim to the **``audit``** tier (verdict stays
                        SUPPORTED) when the host doc is audit-fresh — a human-asserted
                        external fact; otherwise it coerces to ``UNVERIFIABLE``.

    Source-strength precedence: **code > doc-dep > audit > unresolved**. Code-preferring
    — a real source path wins even beside an incidental doc mention or audit fallback,
    so a multi-source claim is judged against its STRONGEST source (code is ground
    truth); `audit` only applies to a claim with no code path and no audited-doc dep.
    ``clean_verified`` is unused (kept for call-site stability)."""
    g = grounding.replace(str(_REPO_ROOT) + "/", "").strip()
    tokens = [t.strip("`,()[]<>\"'") for t in g.split()]
    pathish = [t for t in tokens if t and ("/" in t or "." in t)]
    code = [
        t
        for t in pathish
        if not t.endswith(".md") and not _is_excluded(t) and t not in audited
    ]
    if code:
        return "code"
    # No code path: only an AUDITED doc token OTHER THAN the host doc (one that can
    # become clean) is a trackable dependency. A self-ref (== doc) can't ground its own
    # claim, and an excluded / unknown .md never clears -> both fall to unresolved
    # (where an audit-fresh host doc earns the `audit` tier in `_record_verdicts`).
    if any(t in audited and t != doc for t in pathish):
        return "doc-dep"
    return "unresolved"


def _doc_audit_fresh(doc: str) -> bool:
    """True iff the doc's CURRENT authored body matches its freshness-manifest hash —
    i.e. THIS body was recorded by a human audit (`add_audit_metadata.py`) or by a prior
    clean re-stamp.

    This is the human-vouch signal that puts an `unresolved` claim (no code, no
    audited-doc dependency) on the ``audit`` source tier (verdict SUPPORTED) instead of
    ``UNVERIFIABLE``. It **fails closed** — the machine can never advance the manifest
    hash to a body a human never confirmed:

      * `_restamp` (machine) writes ``manifest[doc] = content_hash(body)`` only for a
        doc judged fully CLEAN.
      * A doc carrying an `unresolved` claim can only be clean once that claim is on the
        ``audit`` tier (SUPPORTED) — which requires THIS check to already pass.

    So the only way the manifest reaches a *new* body holding an unresolved claim is an
    explicit human audit. Edit the prose without re-auditing → hash mismatch → the
    claim falls back to ``UNVERIFIABLE`` and surfaces until a human re-stamps. The body
    hash excludes frontmatter (`content_hash`), so a date-only re-stamp never flips it.
    """
    full = _REPO_ROOT / doc
    try:
        content = full.read_text(encoding="utf-8")
    except OSError:
        return False
    fresh = _freshness()
    return bool(fresh.load_manifest().get(doc) == fresh.content_hash(content))


# --- grounding relations (file/dir content hashing) ------------------------ #


def _semantic_py_hash(data: bytes) -> str:
    """Token-normalized sha256 of Python source — insensitive to whitespace, blank
    lines, indentation style, and comments (all semantic-preserving). A black/isort
    reformat or a comment reword must NOT flip a code grounding hash and falsely
    re-ground every claim grounded on the file; a real code-token change still does.
    Hashes the ``(type, string)`` of each significant token (STRING/docstring tokens
    kept — they can carry a documented default; COMMENT and the whitespace-structure
    tokens dropped). Fail-soft: on a `TokenError`/`IndentationError`/`SyntaxError`
    (a syntactically broken mid-edit read) fall back to the raw-byte hash, so a hash
    is always produced — over-triggering a re-verify, never under."""
    skip = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
    h = hashlib.sha256()
    try:
        for tok in tokenize.tokenize(io.BytesIO(data).readline):
            if tok.type in skip:
                continue
            h.update(f"{tok.type}:{tok.string}\n".encode())
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return hashlib.sha256(data).hexdigest()
    return h.hexdigest()


def _content_fingerprint(data: bytes, suffix: str) -> str:
    """Per-file content fingerprint: a ``.py`` file is token-normalized
    (`_semantic_py_hash`) so a reformat does not flip it; every other file keeps its
    raw-byte hash. Shared by the single-file and directory-member branches below."""
    if suffix == ".py":
        return _semantic_py_hash(data)
    return hashlib.sha256(data).hexdigest()


def _path_content_hash(rel: str) -> str | None:
    """sha256 fingerprint of a grounded path at CURRENT state, or None if it no
    longer exists (deleted file/dir → relation missing → reground the claim).

      * **file** → a ``.py`` file is token-normalized (`_semantic_py_hash`) so a
        black/isort/whitespace/comment reformat does NOT flip it; any other file is
        hashed by its raw bytes.
      * **directory** → hash over the sorted ``(relpath, member-hash)`` of every file
        beneath it, so adding, removing, or editing ANY member flips the hash. This is
        what closes the "new member added to a documented set" gap: a completeness claim
        grounded on a registry directory re-verifies the moment a file lands there.
        A ``.md`` member is hashed by its **authored body** (`content_hash`,
        frontmatter-excluded) — mirroring `_grounding_path_hash` for a direct ``.md``
        dep — so a `last_validated` re-stamp (frontmatter-only) on a member does NOT
        flip the directory hash and falsely re-ground every doc whose completeness claim
        grinds on this directory. A ``.py`` member is token-normalized like a ``.py``
        file (a reformat of one member does not churn the directory hash). Add/remove of
        a member (relpath set changes) or a real body edit still flips it; other members
        keep raw-byte hashing."""
    full = _REPO_ROOT / rel
    if full.is_file():
        try:
            return _content_fingerprint(full.read_bytes(), full.suffix)
        except OSError:
            return None
    if full.is_dir():
        h = hashlib.sha256()
        try:
            for p in sorted(full.rglob("*")):
                if not p.is_file():
                    continue
                rel_parts = p.relative_to(full).parts
                # Skip generated / VCS noise so the hash reflects SOURCE only — a
                # .pyc rewrite or a new __pycache__ entry must NOT flip it (that would
                # re-verify the doc every run for no real change).
                if {".git", "__pycache__", ".mypy_cache", ".pytest_cache"} & set(
                    rel_parts
                ):
                    continue
                if p.suffix in {".pyc", ".pyo"} or p.name.startswith("."):
                    continue
                h.update("/".join(rel_parts).encode("utf-8"))
                if p.suffix == ".md":
                    # Frontmatter-excluded so a date-only re-stamp of a member doc
                    # can't churn the directory hash (see method docstring).
                    h.update(
                        str(
                            _freshness().content_hash(p.read_text(encoding="utf-8"))
                        ).encode("utf-8")
                    )
                else:
                    # `.py` members are token-normalized (reformat-insensitive), every
                    # other member keeps raw bytes — via the shared fingerprint.
                    h.update(
                        _content_fingerprint(p.read_bytes(), p.suffix).encode("utf-8")
                    )
        except OSError:
            return None
        return h.hexdigest()
    return None


def _grounding_path_hash(rel: str) -> str | None:
    """Per-path fingerprint for a grounding relation. A ``.md`` dependency is hashed by
    its **authored body** (`freshness.content_hash`, frontmatter-excluded) so a
    `last_validated` re-stamp — which rewrites only the frontmatter on every clean
    outcome — does NOT flip the hash and re-ground the dependent forever. Any other path
    (code file / directory) keeps the raw-byte ``_path_content_hash`` (no frontmatter).
    ``None`` if the path is missing/unreadable (missing relation → reground)."""
    if rel.endswith(".md"):
        full = _REPO_ROOT / rel
        try:
            return str(_freshness().content_hash(full.read_text(encoding="utf-8")))
        except OSError:
            return None
    return _path_content_hash(rel)


def _code_paths_from_grounding(grounding: str, audited: set[str]) -> list[str]:
    """The repo-relative CODE path tokens named in a grounding string (non-doc,
    non-excluded, not an audited doc). Mirrors `_grounding_tier`'s code-path parse so
    a relation can be derived when the agent omits `grounding_files`. Empty when the
    grounding names only docs or no path."""
    g = grounding.replace(str(_REPO_ROOT) + "/", "").strip()
    tokens = [t.strip("`,()[]<>\"':") for t in g.split()]
    pathish = [t for t in tokens if t and ("/" in t or "." in t)]
    return [
        t
        for t in pathish
        if not t.endswith(".md") and not _is_excluded(t) and t not in audited
    ]


def _doc_paths_from_grounding(grounding: str, audited: set[str], doc: str) -> list[str]:
    """The repo-relative **audited** doc paths a grounding string names — the deps a
    `doc-dep` claim rests on. Drops excluded/unknown `.md` (they never become clean,
    so a claim on one is `unresolved`, not a dependency) and the claim's own doc
    (`dep == doc` self-reference, which would self-block). Sorted + deduped."""
    g = grounding.replace(str(_REPO_ROOT) + "/", "").strip()
    out: set[str] = set()
    for token in g.split():
        rel = token.strip("`,()[]<>\"':")
        if rel in audited and rel != doc:
            out.add(rel)
    return sorted(out)


def _relation_hash(paths: list[str]) -> str | None:
    """Order-independent combined fingerprint of all paths a claim grounds on, or None
    if the list is empty OR any path is unresolvable. Per-path hashing goes through
    `_grounding_path_hash` (`.md` → authored body, else raw bytes) so the record side
    and the `_relation_unchanged` re-check side fingerprint identically."""
    if not paths:
        return None
    parts: list[str] = []
    for rel in sorted(set(paths)):
        ph = _grounding_path_hash(rel)
        if ph is None:
            return None
        parts.append(f"{rel}:{ph}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _relation_unchanged(rec: dict[str, Any]) -> bool:
    """True if a verdict record's grounded files/dirs still hash to what was stored.

    A record with no `grounding_files` (a doc-grounded claim, or one recorded before
    this field existed) carries no code relation → True: it contributes no code-
    staleness signal. Such claims never get skipped on freshness anyway — under the
    code-only-confirms rule they are `UNVERIFIABLE`, so their doc never goes fully
    clean. A stored hash that no longer matches (file edited, dir membership changed,
    path deleted) → False → reground exactly that claim."""
    files = rec.get("grounding_files")
    stored = rec.get("grounding_hash")
    if not files or not stored:
        return True
    return bool(_relation_hash(list(files)) == stored)


def _settle(cache: dict[str, Any]) -> list[str]:
    """Assign each `doc-dep` claim's final ``verdict`` from two drains over the
    dependency graph, mutating records in place. Returns the sorted **stuck** doc paths
    (a doc with a settled-UNVERIFIABLE doc-dep claim) for the needs-human report.

      * **Drain S — structural (verdict-AGNOSTIC):** a doc is *resolvable* if it has
        ≥1 ``code``-tier claim, or every doc it depends on is resolvable. A doc that is
        code-grounded but currently CONTRADICTED is still structurally resolvable (its
        drift is fixable). Whatever never joins is stuck (cycle / orphan, no code exit)
        -> the only path to ``UNVERIFIABLE``.
      * **Drain C — cleanness (verdict-SENSITIVE, least-fixpoint):** a doc is *clean*
        iff every claim's effective verdict is SUPPORTED. A ``doc-dep`` SUPPORTED-raw
        claim is effectively SUPPORTED only when all its deps are clean; else PENDING
        (or UNVERIFIABLE if not resolvable). Iterate to fixpoint.

    Only ``doc-dep`` records with a SUPPORTED raw verdict are gated; a ``doc-dep`` raw
    CONTRADICTED is real drift and is left CONTRADICTED. ``code`` / ``unresolved``
    records are never touched."""
    # Index doc-dep claims and per-doc structure.
    dep_recs: list[dict[str, Any]] = []
    deps_of: dict[str, set[str]] = {}
    has_code: dict[str, bool] = {}
    doc_recs: dict[str, list[dict[str, Any]]] = {}
    for h, rec in cache.items():
        if h == _MARKER_KEY or not isinstance(rec, dict):
            continue
        doc = rec.get("doc")
        if not isinstance(doc, str) or not doc:
            continue
        doc_recs.setdefault(doc, []).append(rec)
        if rec.get("grounding_tier") == "code":
            has_code[doc] = True
        if rec.get("grounding_tier") == "doc-dep" and _raw(rec) == "SUPPORTED":
            dep_recs.append(rec)
            deps_of.setdefault(doc, set()).update(rec.get("grounding_files") or [])

    all_docs = set(doc_recs)

    # Drain S: structural resolvability (verdict-agnostic worklist).
    resolvable = {d for d in all_docs if has_code.get(d)}
    grew = True
    while grew:
        grew = False
        for d in all_docs - resolvable:
            deps = deps_of.get(d)
            if deps and all(dep in resolvable for dep in deps):
                resolvable.add(d)
                grew = True

    def _doc_clean(d: str, clean: set[str]) -> bool:
        recs = doc_recs.get(d) or []
        if not recs:
            return False
        for r in recs:
            if r.get("grounding_tier") == "doc-dep" and _raw(r) == "SUPPORTED":
                deps = r.get("grounding_files") or []
                eff = "SUPPORTED" if deps and all(x in clean for x in deps) else "OPEN"
            else:
                eff = _raw(r)
            if eff != "SUPPORTED":
                return False
        return True

    # Drain C: cleanness least-fixpoint.
    clean: set[str] = set()
    grew = True
    while grew:
        grew = False
        for d in all_docs - clean:
            if _doc_clean(d, clean):
                clean.add(d)
                grew = True

    # Assign each gated doc-dep claim's verdict.
    stuck: set[str] = set()
    for rec in dep_recs:
        dep_files = rec.get("grounding_files") or []
        # No resolvable deps (an unhashable/missing dependency, or a pure self-reference
        # whose only token was the doc itself) can never reach code -> orphan -> stuck.
        if not dep_files or any(dep not in resolvable for dep in dep_files):
            rec["verdict"] = "UNVERIFIABLE"
            stuck.add(rec["doc"])
        elif all(dep in clean for dep in dep_files):
            rec["verdict"] = "SUPPORTED"
        else:
            rec["verdict"] = "PENDING"
    return sorted(stuck)


def _derive_record(
    doc: str,
    claim: str,
    grounding: str,
    verdict: str,
    evidence: str,
    explicit_files: list[str] | None,
    audited: set[str],
    clean_prev: set[str],
) -> tuple[str, dict[str, Any], str]:
    """Deterministically derive ONE cache record from a judged claim — the shared
    classifier behind BOTH `--record` (fresh agent judgments) and `--resettle`
    (cached raw verdicts replayed, no LLM). Classifies the grounding tier, resolves
    the relation file list + hash, and applies the unresolved→audit/UNVERIFIABLE
    promotion. Returns ``(claim_hash, record, raw_verdict)``.

      * **Relation files.** CODE tier: the agent's explicit list, else the code paths
        parsed from the grounding. DOC-DEP tier: the audited dependency doc(s). Hashed
        (.md by authored body, code by raw bytes) so the claim re-grounds when a
        dependency's body moves.
      * **unresolved promotion.** A claim resting on NEITHER code NOR an audited doc is
        not code-backed — the CLI decides from the human-vouch signal, splitting the
        SOURCE (tier) but keeping STATUS honest: audit-FRESH host doc → tier ``audit``,
        verdict SUPPORTED (a human confirmed this body; it is CLEAN); not audit-fresh →
        UNVERIFIABLE (nobody vouched → surfaces as drift). CONTRADICTED is never
        promoted (real drift the agent found); a doc-dep SUPPORTED is left raw for the
        settle to gate.
    """
    tier = _grounding_tier(grounding, audited, clean_prev, doc)
    if tier == "code":
        raw_paths = list(explicit_files or []) or _code_paths_from_grounding(
            grounding, audited
        )
    elif tier == "doc-dep":
        raw_paths = _doc_paths_from_grounding(grounding, audited, doc)
    else:
        raw_paths = []
    gfiles = sorted(
        {
            str(p).replace(str(_REPO_ROOT) + "/", "").strip("`,()[]<>\"' ")
            for p in raw_paths
            if str(p).strip()
        }
    )
    ghash = _relation_hash(gfiles) if gfiles else None
    raw_verdict = verdict
    if tier == "unresolved" and verdict != "CONTRADICTED":
        # Human-vouch on an unresolved claim → audit tier (SUPPORTED). Two independent
        # signals: a standing per-claim confirm order (durable ledger, honoured the
        # instant given and across every sweep) OR the host doc being audit-fresh
        # (whole-doc manifest stamp). Either suffices; neither touches code/doc-dep
        # tiers, so code stays the sole ground truth. CONTRADICTED is never promoted.
        if _claim_confirmed(_claim_hash(claim, grounding)) or _doc_audit_fresh(doc):
            tier = "audit"
            verdict = "SUPPORTED"
            raw_verdict = "SUPPORTED"
        else:
            verdict = "UNVERIFIABLE"
            raw_verdict = "UNVERIFIABLE"
    rec: dict[str, Any] = {
        "doc": doc,
        "claim": claim,
        "grounding": grounding,
        "raw_verdict": raw_verdict,
        "verdict": verdict,
        "grounding_tier": tier,
        "evidence": evidence,
    }
    if gfiles and ghash and tier in ("code", "doc-dep"):
        rec["grounding_files"] = gfiles
        rec["grounding_hash"] = ghash
    h = _claim_hash(claim, grounding)
    return h, rec, raw_verdict


def _record_verdicts(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist judged verdicts to the cache; settle doc-dep claims; re-stamp clean docs.

    The agent emits `verdict ∈ SUPPORTED | CONTRADICTED | UNVERIFIABLE` (never PENDING).
    The CLI re-derives each verdict's grounding tier and records a `raw_verdict` (the
    agent's judgment) alongside the settled `verdict`:

      * **code** → confirms directly (SUPPORTED stands).
      * **doc-dep** (the claim rests on an **audited** doc) → the raw SUPPORTED/
        CONTRADICTED is kept, and a two-drain `_settle` fixpoint assigns the final
        `verdict`: SUPPORTED only while every dependency doc is itself fully clean,
        else a silent **PENDING**, or **UNVERIFIABLE** if the dependency can never
        reach code (cycle / orphan — surfaced to the needs-human report).
      * **unresolved** (an excluded / unknown `.md`, or no path) → a SUPPORTED is
        coerced to **UNVERIFIABLE**.

    The agent submits the **complete** current claim set per doc in one call — fresh
    cached verdicts echoed verbatim AND newly judged ones. The CLI prunes orphans:
    existing records for the doc are replaced by exactly what is submitted. Under-
    submission fails safe (doc looks unclean → re-verified next run). Stores
    `grounding_files` + `grounding_hash` per code AND doc-dep claim (`.md` deps hashed
    by authored body) for relation-driven skip. Settle runs on the same in-RAM cache
    before the single save (in-transaction); only clean docs get re-stamped.
    Returns a per-doc summary for the drift report.
    """
    verdicts = payload.get("verdicts") or []
    cache = _load_cache()
    audited = _audited_doc_set()
    # Snapshot prior cleanness (passed to the tier classifier for call-site stability).
    # Cross-doc trust is now resolved by `_settle` over the whole cache, not from this
    # snapshot — a mutually-referencing cycle settles to UNVERIFIABLE, not vacuous.
    clean_prev = _clean_verified_docs(cache)
    # Prune orphans: a re-record REPLACES a doc's records (the agent submits the
    # complete current claim set per doc, echoing reused/fresh verdicts verbatim).
    # Drop every existing record for the docs in this payload first, so a claim the
    # prose no longer makes can't keep re-verifying the doc (cache-driven skip reads
    # every record of a doc) or skew its cleanliness. Under-submission fails safe:
    # the doc looks unclean → re-verified, never falsely skipped.
    docs_in_payload = {
        v.get("doc")
        for v in verdicts
        if v.get("doc") in audited and (v.get("verdict") or "").upper() in _VERDICTS
    }
    cache = {
        h: r
        for h, r in cache.items()
        if h == _MARKER_KEY
        or not (isinstance(r, dict) and r.get("doc") in docs_in_payload)
    }
    per_doc: dict[str, dict[str, list[Any]]] = {}

    for v in verdicts:
        doc = v.get("doc")
        claim = v.get("claim", "")
        grounding = v.get("grounding", "")
        verdict = (v.get("verdict") or "").upper()
        if not doc or verdict not in _VERDICTS:
            continue
        # Guard: only record verdicts for docs Layer B actually owns. A verdict for
        # a non-audited or excluded path (CHANGELOG, superpowers/, .planning/, a
        # stray file) is dropped — it must never cache nor trigger a re-stamp.
        if doc not in audited:
            continue
        h, rec, raw_verdict = _derive_record(
            doc,
            claim,
            grounding,
            verdict,
            v.get("evidence", ""),
            v.get("grounding_files"),
            audited,
            clean_prev,
        )
        verdict = rec["verdict"]
        cache[h] = rec
        slot = per_doc.setdefault(
            doc,
            {"SUPPORTED": [], "CONTRADICTED": [], "UNVERIFIABLE": [], "PENDING": []},
        )
        item: dict[str, Any] = {"claim": claim, "evidence": v.get("evidence", "")}
        slot[raw_verdict if raw_verdict in slot else verdict].append(item)

    # Settle doc-dep claims on the SAME in-RAM cache, then save ONCE (in-transaction —
    # no second load/save TOCTOU). Settle assigns SUPPORTED/PENDING/UNVERIFIABLE from
    # the whole cache, so a doc-dep in THIS payload sees deps recorded in earlier runs.
    stuck = _settle(cache)
    _save_cache(cache)

    # Clean docs = re-derive from the SETTLED cache (a doc-dep demoted to PENDING must
    # NOT re-stamp), intersected with this payload's docs (only judge what we just saw).
    settled_clean = _clean_verified_docs(cache)
    clean_docs = [doc for doc in per_doc if doc in settled_clean]
    restamped = _restamp(clean_docs) if clean_docs else []
    # Needs-human report: written iff every audited doc judged once AND a stuck set
    # remains. Fail-soft — never break a --record.
    try:
        _refresh_needs_human_report(cache, stuck)
    except Exception:
        pass
    # Count `audit`-tier claims (SUPPORTED-by-human-vouch, no code referent) across the
    # docs in this payload, for the honest one-line report banner.
    audit_grounded = sum(
        1
        for r in cache.values()
        if isinstance(r, dict)
        and r.get("doc") in per_doc
        and r.get("grounding_tier") == "audit"
    )
    return {
        "per_doc": per_doc,
        "clean": clean_docs,
        "restamped": restamped,
        "audit_grounded": audit_grounded,
    }


def _resettle() -> dict[str, Any]:
    """Re-run ONLY the deterministic half — tier classification + the settle fixpoint —
    over already-judged verdicts, WITHOUT re-invoking the agent/LLM. The prose-vs-code
    judgment is the expensive part and is keyed on (prose, grounded code); it is NEVER
    recomputed here. What this DOES recompute is everything downstream of a *settle
    input* that can move without the doc's own prose or code changing:

      * the ``_grounding_tier`` logic itself (a verifier bug-fix / classifier change),
      * a dependency doc's cleanliness (a doc-dep claim settles when its dep is clean),
      * an audit stamp (an ``unresolved`` claim's audit-tier promotion / demotion).

    Each cached record's stored ``raw_verdict`` (the agent's original judgment, kept
    FIXED) is replayed through ``_derive_record`` + ``_settle``. A record whose host doc
    is no longer audited is pruned. Re-stamping is SCOPED: only docs whose settled
    outcome actually CHANGED this run are re-stamped (and only if now clean) — an
    untouched clean doc keeps its existing ``last_validated``, so a re-settle never
    re-claims today's date across the whole audited set. Returns the same summary shape
    as ``_record_verdicts``, with ``per_doc`` limited to the changed docs.
    """
    cache = _load_cache()
    audited = _audited_doc_set()
    clean_prev = _clean_verified_docs(cache)
    # Key the prior outcome by the RECOMPUTED claim hash (== the post-replay key), so
    # change detection is stable even if a record was stored under a legacy key.
    before: dict[str, tuple[Any, Any]] = {}
    before_doc: dict[str, str] = {}
    for h, r in cache.items():
        if h == _MARKER_KEY or not isinstance(r, dict):
            continue
        doc = r.get("doc")
        if not isinstance(doc, str):
            continue
        bh = _claim_hash(r.get("claim", ""), r.get("grounding", ""))
        before[bh] = (r.get("verdict"), r.get("grounding_tier"))
        before_doc[bh] = doc
    new_cache: dict[str, Any] = {}
    if _MARKER_KEY in cache:
        new_cache[_MARKER_KEY] = cache[_MARKER_KEY]
    doc_of: dict[str, set[str]] = {}  # doc -> set of its claim hashes (new)
    for h, r in cache.items():
        if h == _MARKER_KEY or not isinstance(r, dict):
            continue
        doc = r.get("doc")
        if not isinstance(doc, str) or doc not in audited:
            continue  # prune records whose doc is no longer audited
        raw = (r.get("raw_verdict") or r.get("verdict") or "").upper()
        if raw not in _VERDICTS:
            continue
        nh, nrec, _rawv = _derive_record(
            doc,
            r.get("claim", ""),
            r.get("grounding", ""),
            raw,
            r.get("evidence", ""),
            r.get("grounding_files"),
            audited,
            clean_prev,
        )
        new_cache[nh] = nrec
        doc_of.setdefault(doc, set()).add(nh)

    stuck = _settle(new_cache)
    _save_cache(new_cache)

    after = {
        h: (r.get("verdict"), r.get("grounding_tier"))
        for h, r in new_cache.items()
        if h != _MARKER_KEY and isinstance(r, dict)
    }
    # A doc CHANGED if any of its (new or vanished) records' settled outcome differs.
    changed_docs: set[str] = set()
    for doc, hashes in doc_of.items():
        if any(before.get(h) != after.get(h) for h in hashes):
            changed_docs.add(doc)
    for bh in before:
        if bh not in after:  # a record was pruned (doc de-audited / claim re-keyed)
            changed_docs.add(before_doc[bh])

    settled_clean = _clean_verified_docs(new_cache)
    restamp_targets = sorted(d for d in changed_docs if d in settled_clean)
    restamped = _restamp(restamp_targets) if restamp_targets else []
    try:
        _refresh_needs_human_report(new_cache, stuck)
    except Exception:
        pass

    # Report the FULL post-settle drift across every doc (so a still-open CONTRADICTED/
    # UNVERIFIABLE that did not move is never hidden) — `_render_report` lists only the
    # open ones. Re-stamping above stayed scoped to docs whose outcome actually changed.
    per_doc: dict[str, dict[str, list[Any]]] = {}
    for doc, hashes in doc_of.items():
        slot = per_doc.setdefault(
            doc,
            {"SUPPORTED": [], "CONTRADICTED": [], "UNVERIFIABLE": [], "PENDING": []},
        )
        for h in hashes:
            r = new_cache[h]
            key = r["verdict"] if r["verdict"] in slot else "SUPPORTED"
            slot[key].append(
                {"claim": r.get("claim", ""), "evidence": r.get("evidence", "")}
            )
    audit_grounded = sum(
        1
        for r in new_cache.values()
        if isinstance(r, dict) and r.get("grounding_tier") == "audit"
    )
    return {
        "per_doc": per_doc,
        "clean": restamp_targets,
        "restamped": restamped,
        "audit_grounded": audit_grounded,
    }


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


def _confirm_claims(paths: list[str]) -> dict[str, Any]:
    """Record a durable human-confirm order for the still-open EXTERNAL claims of the
    named docs, then re-settle so the verdicts flip SUPPORTED immediately.

    This is the one-step "mark verified by human" order. It is COMPLETE the moment it
    runs: the order is written to the durable ledger (`_CONFIRMED_LEDGER`) — which no
    later `--record` can erase — and a `_resettle` applies it to the verdict cache in
    the same call, re-stamping the now-clean docs. No separate manifest re-stamp or
    follow-up sweep is required.

    Scope is enforced here (decision: only no-code externals). A claim is confirmable
    only when its grounding tier is ``unresolved`` (no code path, no audited-doc dep).
    A ``code`` / ``doc-dep`` claim is REFUSED with guidance — code stays the sole
    ground truth, so such a claim must first be re-prosed to drop its code referent
    (becoming external) before a human may vouch for it. A claim already SUPPORTED is
    skipped (nothing to confirm). Returns ``{confirmed, refused, skipped, resettle}``.
    """
    audited = _audited_doc_set()
    cache = _load_cache()
    ledger = _load_confirmed()
    today = date.today().isoformat()
    wanted = {p for p in paths if p in audited}
    confirmed: list[dict[str, str]] = []
    refused: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for r in cache.values():
        if not isinstance(r, dict) or r.get("doc") not in wanted:
            continue
        doc = r["doc"]
        claim = r.get("claim", "")
        grounding = r.get("grounding", "")
        tier = r.get("grounding_tier")
        verdict = (r.get("verdict") or "").upper()
        row = {"doc": doc, "claim": claim, "tier": tier or "?"}
        if verdict == "SUPPORTED" and tier != "audit":
            skipped.append(row)  # already confirmed against code/doc-dep
            continue
        if tier in ("code", "doc-dep"):
            refused.append(row)  # code is ground truth — re-prose to external first
            continue
        # unresolved (or already audit-tier) → confirmable external claim.
        h = _claim_hash(claim, grounding)
        ledger[h] = {
            "doc": doc,
            "claim": claim,
            "grounding": grounding,
            "confirmed_by": "human",
            "confirmed_at": today,
        }
        confirmed.append(row)
    if confirmed:
        _save_confirmed(ledger)
    # Apply immediately: replay cached raw verdicts through the now-updated ledger so
    # the freshly-confirmed claims become audit-tier SUPPORTED and clean docs re-stamp.
    resettle = _resettle() if confirmed else {"per_doc": {}, "restamped": []}
    return {
        "confirmed": confirmed,
        "refused": refused,
        "skipped": skipped,
        "resettle": resettle,
    }


def _render_confirm(result: dict[str, Any]) -> str:
    """One-screen human summary of a `--confirm` order: what was vouched, what was
    refused (and why), and which docs re-stamped clean."""
    lines: list[str] = []
    conf = result.get("confirmed", [])
    ref = result.get("refused", [])
    skip = result.get("skipped", [])
    restamped = (result.get("resettle") or {}).get("restamped", [])
    if conf:
        lines.append(
            f"Human-confirmed {len(conf)} external claim(s) → SUPPORTED (audit tier):"
        )
        lines += [f"  ✓ {c['doc']}: {c['claim'][:80]}" for c in conf]
    if restamped:
        lines.append("Re-stamped clean: " + ", ".join(sorted(restamped)))
    if ref:
        lines.append(
            f"\nREFUSED {len(ref)} code-grounded claim(s) — code is ground truth. "
            "FIRST read the live prose, don't trust this cached tier:\n"
            "  • prose already external (e.g. 'library default, not overridden')? "
            "the `code` grounding is STALE — re-sweep the doc so the agent re-grounds "
            "it (likely → SUPPORTED, code tier). Do NOT re-prose.\n"
            "  • prose really names our code? re-prose to drop the referent, then "
            "re-sweep + confirm."
        )
        lines += [f"  ✗ [{c['tier']}] {c['doc']}: {c['claim'][:80]}" for c in ref]
    if skip:
        lines.append(f"\nSkipped {len(skip)} already-supported claim(s).")
    if not (conf or ref or skip):
        lines.append(
            "No open external claims on the named doc(s) — nothing to confirm."
        )
    return "\n".join(lines)


def _render_report(summary: dict[str, Any]) -> str:
    """Human drift report: CONTRADICTED + UNVERIFIABLE per doc. PENDING is deliberately
    NOT listed — a transient, silent 'waiting on a not-yet-clean dependency' state,
    surfaced to a human only if it later proves genuinely stuck (needs-human report).
    """
    per_doc = summary["per_doc"]
    lines: list[str] = []
    drift = 0

    def _open(s: dict[str, list[Any]]) -> list[Any]:
        return s["CONTRADICTED"] + s["UNVERIFIABLE"]

    for doc in sorted(per_doc):
        s = per_doc[doc]
        if not _open(s):
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
    n_docs = sum(1 for d in per_doc if _open(per_doc[d]))
    head = f"Doc verification: {drift} open item(s) across {n_docs} doc(s)."
    n_audit = summary.get("audit_grounded", 0)
    if n_audit:
        head += (
            f"\n{n_audit} claim(s) grounded by human audit "
            "(audit tier — no code referent; vouched by the freshness stamp)."
        )
    if summary["restamped"]:
        head += f"\nRe-stamped {len(summary['restamped'])} clean doc(s): " + ", ".join(
            summary["restamped"]
        )
    if drift == 0:
        head += "\nNo open items. (Advisory: LLM judge is probabilistic.)"
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
    "--base",
    default=None,
    help="Base ref for --changed net diff (default: the previous `release:` "
    "commit; `main` is degenerate here — unrelated histories).",
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
    "--resettle",
    "resettle",
    is_flag=True,
    help=(
        "Re-run the deterministic settle (no LLM): replay cached raw verdicts through "
        "the current tier/settle logic. Use when a SETTLE INPUT moved without prose/"
        "code changing — a verifier-logic fix, a dependency doc going clean, or an "
        "audit stamp. Re-stamps only docs whose outcome changed."
    ),
)
@click.option(
    "--confirm",
    "confirm",
    is_flag=True,
    help=(
        "Human-confirm the open EXTERNAL claims of the named PATHS as verified (a "
        "durable, one-step order). Writes the standing confirm ledger and re-settles "
        "so they flip SUPPORTED (audit tier) immediately. Refuses code-grounded "
        "claims — re-prose those to drop the code referent first."
    ),
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
    "--force",
    is_flag=True,
    help=(
        "Re-verify even docs whose prose AND grounded code are unchanged — the "
        "manual full re-verify (use with --all). Default skipping is relation-"
        "driven: a doc is skipped only while its prose and every grounded file/dir "
        "are unchanged, so an idle repo costs nothing and there is no time window."
    ),
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
    base: str | None,
    record_file: str | None,
    check_marker: bool,
    resettle: bool,
    confirm: bool,
    url: str | None,
    top_k: int,
    force: bool,
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
    Skipping is RELATION-DRIVEN (no time window): a doc is dropped only while its
    authored prose AND every grounded file/dir are unchanged. An idle repo costs
    nothing; any change re-enters the doc automatically. Docs never prose-judged
    (human-audit stamp only) and code-affected entries are never skipped.
    For a full manual re-verify: --all --force.

    \b
    Record judged verdicts (the agent pipes them back):
      brainpalace verify-docs --record verdicts.json
      brainpalace verify-docs --record -            # stdin
    payload {verdicts:[{doc,claim,grounding,grounding_files?,verdict,evidence}]},
    verdict ∈ SUPPORTED|CONTRADICTED|UNVERIFIABLE (the agent never emits PENDING). The
    agent submits the COMPLETE current claim set per doc (fresh cached verdicts echoed
    verbatim + new judgments). The CLI re-derives each grounding's tier: code →
    confirms; an audited-doc dependency (doc-dep) → settled to SUPPORTED/PENDING/
    UNVERIFIABLE by a two-drain fixpoint (PENDING is a silent transient; UNVERIFIABLE
    means a human is needed, see .claude/doc-verify-needs-human.md); an excluded/unknown
    .md → UNVERIFIABLE. Stores grounding_files + grounding_hash per code AND doc-dep
    claim (.md deps hashed by authored body). Clean docs are re-stamped; the report
    lists CONTRADICTED + UNVERIFIABLE (PENDING stays silent).
    """
    _require_repo()
    if base is None:
        base = _default_base()
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

    if confirm:
        # Durable human-confirm order: vouch the named docs' open EXTERNAL claims and
        # re-settle so they go SUPPORTED now. The order persists in the ledger, so it
        # survives even if no later sweep runs. Refuses code-grounded claims.
        if not paths:
            raise SystemExit(
                "verify-docs --confirm: name the doc PATHS whose external claims you "
                "are confirming. See --help."
            )
        result = _confirm_claims(list(paths))
        _stamp_weekly_clock()
        if json_output:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(_render_confirm(result))
        return

    if resettle:
        # Deterministic re-settle (no LLM): replay cached raw verdicts through the
        # current tier/settle logic. For settle-input changes (verifier-logic fix, a
        # dependency going clean, an audit stamp) — never re-judges prose vs code.
        summary = _resettle()
        if json_output:
            click.echo(json.dumps(summary, indent=2))
        else:
            click.echo(_render_report(summary))
        return

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

    # Progress banner for this round (stderr — stdout carries the JSON packet). A
    # snapshot of the whole project-doc set, independent of this batch's filtering.
    click.echo(
        _render_stats(_verification_stats(_load_cache(), _audited_doc_set())),
        err=True,
    )

    entries = _resolve_docs(
        all_docs=all_docs, changed=changed, base=base, paths=paths, url=url, top_k=top_k
    )
    # Classify-or-refuse: a glob-matched doc absent from the freshness manifest is an
    # UNCLASSIFIED new surface (could be a real new doc, could be plugin scratch that
    # landed under a tracked dir). Never auto-verify it in a sweep — drop + warn. It
    # is verifiable the moment it is named explicitly (naming = classifying it real);
    # otherwise the human excludes it. Skipped for explicit paths (already named).
    manifest = _freshness().load_manifest()
    entries, unclassified = _filter_unclassified(entries, manifest)
    if unclassified:
        click.echo(
            f"verify-docs: {len(unclassified)} unclassified new doc surface(s) not "
            f"auto-verified: {', '.join(unclassified)}.\n"
            "  → real doc?  verify it explicitly: brainpalace verify-docs <path>\n"
            "  → scratch?   add it to _EXCLUDE_FILES/_EXCLUDE_PREFIXES in "
            "verify_docs.py (and narrow DEFAULT_GLOBS if it shouldn't be tracked).",
            err=True,
        )
    # Relation-driven skip (no time window): drop docs whose prose AND every
    # grounded file/dir are unchanged. Code-affected entries (--changed via index)
    # are always kept — the code they document moved. --force skips nothing.
    protected = [e for e in entries if e.get("trigger") == "code-affected"]
    filterable = [e for e in entries if e.get("trigger") != "code-affected"]
    kept, skipped = _filter_fresh(filterable, force=force)
    entries = protected + kept
    if skipped:
        # stderr — stdout carries the JSON packet the agent parses.
        click.echo(
            f"verify-docs: skipped {len(skipped)} unchanged doc(s) "
            f"(prose + grounded code unchanged): {', '.join(skipped)}. "
            "Use --force to re-verify them anyway.",
            err=True,
        )
    # Order smallest-prose-first so cheap docs (and, by correlation, dependency leaves)
    # lead and a budget-capped batch clears more docs. Final sort — after every filter.
    entries = _order_by_cost(entries)
    # Nothing left to judge: surface the needs-human report iff verification is stuck.
    # The settle (in --record) maintains it; here we only echo its existence so a sweep
    # that finds nothing tells the human why.
    if not entries and _NEEDS_HUMAN_REPORT.exists():
        click.echo(
            f"verify-docs: no docs left to judge — see {_NEEDS_HUMAN_REPORT} for "
            "doc-dep claims that need a human decision.",
            err=True,
        )
    # Grounding needs the server. If there is anything to judge, ensure it is up —
    # try one restart, and STOP (emit no packet) if that fails, rather than let the
    # agent ground against a dead server and record false UNVERIFIABLE verdicts.
    if entries and not _ensure_server_up(url):
        raise SystemExit(
            "verify-docs: index server is unreachable and auto-restart failed. "
            "Grounding every claim needs it — start it manually (`brainpalace "
            "start`), confirm `brainpalace status`, then re-run. Nothing was "
            "judged or recorded."
        )
    # The packet IS the machine contract the agent consumes — always JSON on
    # resolve (`--json` is accepted for symmetry/explicitness but is the default).
    packet = _build_packet(entries, base if changed else "-")
    # Actionable count for THIS round (stderr — stdout carries the JSON packet).
    click.echo(_render_packet_count(len(packet.get("docs", []))), err=True)
    click.echo(json.dumps(packet, indent=2))

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
import os
import subprocess
import sys
import tempfile
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


# --- recently-verified skip (the --all "skip-fresh" filter) ---------------- #
#: Default fresh window (days). Tuned to sit BELOW the weekly-sweep cadence (7d)
#: so last week's sweep is always re-verified this week, yet ABOVE the multi-day
#: span of a single sweep so a sweep dragged across sessions/days doesn't re-judge
#: docs it already covered. See the command help + brainpalace-verify-docs.md.
DEFAULT_SKIP_FRESH_DAYS = 6


def _parse_iso_date(value: str | None) -> date | None:
    """Parse a `last_validated` 'YYYY-MM-DD' string to a date, or None if missing
    or unparseable (an un-dated / malformed doc is treated as stale → never
    skipped, the safe default)."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _prose_verified_docs() -> set[str]:
    """Repo-relative paths that have ≥1 prose verdict in the verdict cache — i.e.
    docs the Layer-B prose verifier has actually judged.

    This is the **provenance signal** skip-fresh needs. `last_validated` alone is
    ambiguous: it is written by BOTH `add_audit_metadata.py` (the human "confirmed
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
    entries: list[dict[str, Any]], days: int, reset_epoch: date | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split resolved entries into (kept, skipped). A doc is **fresh** — and
    skipped — only when ALL hold:

      * it has actually been **prose-verified** (≥1 verdict in the verdict cache);
        a doc whose `last_validated` came only from the human audit tool but was
        never judged by Layer B is NEVER skipped, AND
      * `last_validated` is newer than `days` ago (age < days), AND
      * its authored content still matches the freshness manifest hash (i.e. it
        has NOT been edited since it was validated), AND
      * it was validated **on or after** `reset_epoch` (the verification-baseline
        reset written by `--reset`); a doc stamped before the reset is stale until
        re-verified this cycle. `reset_epoch=None` disables that gate.

    The hash guard is what makes "always skip fresh" safe: a doc you just edited
    has a stale stamp but a changed hash, so it is kept (re-verified) — you never
    silently skip a doc whose prose moved. A doc never prose-judged, `days`-or-more
    old, un-dated, edited-since, unreadable, validated-before-reset, or absent from
    the manifest is kept. The caller decides WHICH entries to pass here
    (code-affected entries are exempt — their prose is unchanged yet the code they
    document moved)."""
    fresh = _freshness()
    today = date.today()
    manifest = fresh.load_manifest()
    verified = _prose_verified_docs()
    kept: list[dict[str, Any]] = []
    skipped: list[str] = []
    for e in entries:
        full = _REPO_ROOT / e["path"]
        try:
            content = full.read_text(encoding="utf-8")
        except OSError:
            kept.append(e)
            continue
        stamped = _parse_iso_date(fresh.last_validated(content))
        recent = stamped is not None and (today - stamped).days < days
        unchanged = manifest.get(e["path"]) == fresh.content_hash(content)
        after_reset = reset_epoch is None or (
            stamped is not None and stamped >= reset_epoch
        )
        prose_verified = e["path"] in verified
        if prose_verified and recent and unchanged and after_reset:
            skipped.append(e["path"])
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

#: Human-facing deadlock report (repo-dev scope, gitignore-able). Written ONLY when
#: verification is genuinely stuck — every doc has been judged once and a set of
#: still-unverified docs is mutually cross-dependent (a `blocked_on` cycle/orphan
#: with no path to code). Deleted when no such deadlock remains. Its mere existence
#: means "a human must break a cycle." NOT under docs/ — never an audited doc.
_BLOCKED_REPORT = _REPO_ROOT / ".claude" / "doc-verify-blocked.md"


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


def _load_reset_epoch() -> date | None:
    """The verification-baseline reset date (`verify_reset_at`) written by
    `--reset`, or None if never reset. Docs validated before it are treated as
    stale by `_filter_fresh` until re-verified. Fail-soft."""
    return _parse_iso_date(_read_sweep_state().get("verify_reset_at"))


def _stamp_reset() -> str:
    """Record TODAY as the verification-baseline reset epoch and return it.
    Mutates no docs — only the gitignored sweep-state file."""
    today = date.today().isoformat()
    state = _read_sweep_state()
    state["verify_reset_at"] = today
    _write_sweep_state(state)
    return today


# --- packet emit ----------------------------------------------------------- #


def _build_packet(entries: list[dict[str, Any]], base: str) -> dict[str, Any]:
    """Assemble the work packet the agent judges: per doc, the verifiable prose +
    any **terminal** cached verdicts (so the agent self-skips unchanged claim pairs).

    Only SUPPORTED/CONTRADICTED are fed back as reusable: a BLOCKED or UNVERIFIABLE
    claim is deliberately omitted so the agent **re-grounds and re-judges** it — its
    blocking dependency may have been verified since (BLOCKED), or the index may now
    return code (UNVERIFIABLE). This is the "only re-check the leftover claims"
    contract: clean claims cost nothing, the open subset always retries."""
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
            if isinstance(rec, dict)
            and rec.get("doc") == rel
            and (rec.get("verdict") or "").upper() in _TERMINAL_VERDICTS
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

#: A claim's judged outcome. BLOCKED is non-terminal: the claim has no code
#: referent and grounds only on an *unverified* doc, so it can't be confirmed yet
#: but MAY clear once that dependency is verified (the defer scheduler re-queues it
#: then). SUPPORTED/CONTRADICTED are terminal (reused from cache); UNVERIFIABLE is
#: terminal-for-now (retrieval found nothing — needs code/human, never auto-defers).
_VERDICTS = ("SUPPORTED", "CONTRADICTED", "UNVERIFIABLE", "BLOCKED")

#: Verdicts safe to REUSE from the cache without re-judging. Only the terminal ones:
#: a BLOCKED/UNVERIFIABLE claim must be retried (its dependency may have cleared, or
#: the index improved), so it is deliberately excluded and re-grounded each run.
_TERMINAL_VERDICTS = frozenset({"SUPPORTED", "CONTRADICTED"})

#: Verdicts that mean a doc is NOT clean (any of these blocks the re-stamp).
_OPEN_VERDICTS = frozenset({"CONTRADICTED", "UNVERIFIABLE", "BLOCKED"})


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
    """Repo-relative paths of docs that are FULLY clean in the cache — every
    recorded verdict SUPPORTED, none CONTRADICTED/UNVERIFIABLE/BLOCKED. These are
    the only docs that may serve as trustworthy grounding for *another* doc's claim:
    their own claims have already been confirmed against code (transitively). A doc
    with ≥1 verdict but any open verdict is NOT clean, so it can't launder onward."""
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
      * ``full``    — fully verified (every claim SUPPORTED; re-stamped),
      * ``partial`` — judged but with ≥1 open item (CONTRADICTED/UNVERIFIABLE/
                      BLOCKED) — i.e. seen but not clean,
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


def _doc_blocked_state(cache: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-doc deferral state derived from the cache:
    * ``blocked_on``     — union of unverified-doc deps across the doc's BLOCKED
                           claims (the docs it is waiting on).
    * ``has_block``      — the doc has ≥1 BLOCKED claim.
    * ``has_other_open`` — the doc has a CONTRADICTED/UNVERIFIABLE claim (real
                           drift / ungroundable) — so it is NOT merely waiting on a
                           dependency and must stay in the packet, not be deferred.
    """
    per: dict[str, dict[str, Any]] = {}
    for h, rec in cache.items():
        if h == _MARKER_KEY or not isinstance(rec, dict):
            continue
        doc = rec.get("doc")
        if not isinstance(doc, str) or not doc:
            continue
        v = (rec.get("verdict") or "").upper()
        s = per.setdefault(
            doc, {"blocked_on": set(), "has_block": False, "has_other_open": False}
        )
        if v == "BLOCKED":
            s["has_block"] = True
            s["blocked_on"].update(rec.get("blocked_on") or [])
        elif v in ("CONTRADICTED", "UNVERIFIABLE"):
            s["has_other_open"] = True
    return per


def _blocked_on_from_grounding(
    grounding: str, audited: set[str], clean_verified: set[str]
) -> list[str]:
    """The unverified audited docs a grounding string names — the deps a BLOCKED
    claim waits on. Excluded docs (CHANGELOG) are NOT deps: they never clear, so a
    claim resting on one is ungroundable (UNVERIFIABLE), not deferrable."""
    deps: list[str] = []
    g = grounding.replace(str(_REPO_ROOT) + "/", "").strip()
    for token in g.split():
        rel = token.replace(str(_REPO_ROOT) + "/", "").strip("`,()[]")
        if rel in audited and rel not in clean_verified and rel not in deps:
            deps.append(rel)
    return deps


# --- defer scheduler + deadlock report ------------------------------------- #


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


def _filter_blocked(
    entries: list[dict[str, Any]], cache: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split resolved entries into (kept, deferred). A doc is **deferred** — dropped
    from this run's packet — only when ALL hold:

      * it has ≥1 BLOCKED claim and NO CONTRADICTED/UNVERIFIABLE claim (purely
        waiting on a dependency, not itself drifted/ungroundable — a drifted doc
        stays in the packet so its real findings keep surfacing), AND
      * it is **unchanged** since last judged (manifest-hash match — an edited doc
        always re-judges; its claims may have moved), AND
      * **every** doc it is `blocked_on` is still NOT clean (if any blocker has been
        verified since, the doc re-activates so its blocked claim can resolve), AND
      * it was not named as an **explicit path** and is not `code-affected` (those
        are deliberate "judge this now" requests — never deferred).

    Deferral is what stops a blocked doc being re-queued every batch: it re-enters
    only when a blocker clears (cascading topologically), and a true cross-dependent
    cycle — whose blockers never clear — is simply never re-queued (zero budget;
    surfaced by the deadlock report instead)."""
    fresh = _freshness()
    manifest = fresh.load_manifest()
    clean = _clean_verified_docs(cache)
    states = _doc_blocked_state(cache)
    kept: list[dict[str, Any]] = []
    deferred: list[str] = []
    for e in entries:
        rel = e["path"]
        st = states.get(rel)
        if (
            e.get("trigger") in ("explicit", "code-affected")
            or not st
            or not st["has_block"]
            or st["has_other_open"]
        ):
            kept.append(e)
            continue
        try:
            content = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        except OSError:
            kept.append(e)
            continue
        unchanged = manifest.get(rel) == fresh.content_hash(content)
        deps = st["blocked_on"]
        blockers_open = bool(deps) and all(d not in clean for d in deps)
        if unchanged and blockers_open:
            deferred.append(rel)
        else:
            kept.append(e)
    return kept, deferred


def _weak_components(
    nodes: set[str], states: dict[str, dict[str, Any]]
) -> list[set[str]]:
    """Weakly-connected components of the deadlocked set over `blocked_on` edges —
    so the report shows each mutual cycle as one group (and orphans as singletons).
    Union-find over edges whose BOTH ends are in `nodes`."""
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for d in nodes:
        for dep in states.get(d, {}).get("blocked_on", set()):
            if dep in parent:
                parent[find(d)] = find(dep)
    groups: dict[str, set[str]] = {}
    for n in nodes:
        groups.setdefault(find(n), set()).add(n)
    return list(groups.values())


def _deadlocked_docs(
    cache: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Compute the deadlocked set: BLOCKED docs that can NEVER reach code. Seed the
    `resolvable` set with the clean docs, then drain — a BLOCKED doc becomes
    resolvable once every doc it waits on is resolvable. Whatever never drains is a
    cross-dependent cycle or an orphan with no code exit. Returns (sorted deadlocked
    paths, the per-doc state map) so the caller can render claims/edges."""
    clean = _clean_verified_docs(cache)
    states = _doc_blocked_state(cache)
    blocked_docs = {d for d, s in states.items() if s["has_block"]}
    resolvable: set[str] = set(clean)
    grew = True
    while grew:
        grew = False
        for d in blocked_docs - resolvable:
            deps = states[d]["blocked_on"]
            if deps and all(dep in resolvable for dep in deps):
                resolvable.add(d)
                grew = True
    return sorted(blocked_docs - resolvable), states


def _refresh_blocked_report(cache: dict[str, Any]) -> list[str]:
    """Write the deadlock report when (and only when) verification is genuinely
    stuck — every audited doc has been judged at least once AND a cross-dependent
    BLOCKED set remains with no path to code. Otherwise delete any stale report
    (there is still progress to make, or the deadlock cleared). Returns the
    deadlocked paths (empty when none)."""
    audited = _audited_doc_set()
    judged = _docs_with_verdicts(cache)
    # Docs never looked at yet: while any remain, draining them may break a cycle,
    # so "cannot proceed further" is not yet true — don't cry deadlock.
    unjudged = {d for d in audited if d not in judged and not _is_excluded(d)}
    deadlocked, states = _deadlocked_docs(cache)
    if unjudged or not deadlocked:
        if _BLOCKED_REPORT.exists():
            _BLOCKED_REPORT.unlink()
        return []
    _write_blocked_report(deadlocked, states, cache)
    return deadlocked


def _write_blocked_report(
    deadlocked: list[str], states: dict[str, dict[str, Any]], cache: dict[str, Any]
) -> None:
    """Render the human deadlock report grouped by cycle. Lists each doc's BLOCKED
    claims and the docs it waits on, plus how to break the loop."""
    dead = set(deadlocked)
    blocked_claims: dict[str, list[dict[str, Any]]] = {}
    for h, rec in cache.items():
        if h == _MARKER_KEY or not isinstance(rec, dict):
            continue
        doc = rec.get("doc")
        if doc in dead and (rec.get("verdict") or "").upper() == "BLOCKED":
            blocked_claims.setdefault(doc, []).append(rec)
    lines = [
        "# Doc verification — blocked (human action needed)",
        "",
        f"Generated {date.today().isoformat()}. Every audited doc has been judged, "
        "but the docs below cannot be verified: their remaining claims ground only "
        "on other **unverified** docs (a cross-dependent cycle or an orphan with no "
        "path to code). The verifier will not re-queue them until a human breaks the "
        "loop — ground one claim on code, rewrite it to cite a verified doc, or "
        "manually stamp the doc (scripts/add_audit_metadata.py) if it is canonical.",
        "",
    ]
    components = sorted(_weak_components(dead, states), key=lambda c: sorted(c)[0])
    for i, comp in enumerate(components, 1):
        members = sorted(comp)
        if len(members) > 1:
            label = " ↔ ".join(Path(m).name for m in members)
            header = f"## Cycle {i}: {label}"
        else:
            header = f"## Orphan {i}: {Path(members[0]).name}"
        lines.append(header)
        for d in members:
            lines.append(f"- {d}")
            for rec in blocked_claims.get(d, []):
                deps = ", ".join(rec.get("blocked_on") or []) or "(unverified doc)"
                lines.append(f"  - claim: {rec.get('claim', '')}")
                lines.append(f"    blocked_on: {deps}")
        lines.append("")
    _BLOCKED_REPORT.parent.mkdir(parents=True, exist_ok=True)
    _BLOCKED_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _grounding_tier(grounding: str, audited: set[str], clean_verified: set[str]) -> str:
    """Classify a claim's grounding by source-of-truth strength. **Fails CLOSED:**
    the only way to earn the trusted `code` tier is a real non-doc source path —
    anything unrecognized (a stray `.md`, an empty or vague grounding, a typo'd or
    moved path) is NOT trusted, because letting it pass as `code` is the exact bug
    class this whole layer exists to prevent.

      * ``code``           — a non-doc source path token (e.g. `*.py`, tests,
                             config). Code IS the ground truth; the only tier that
                             re-stamps a doc.
      * ``verified-doc``   — an audited doc that is itself FULLY clean (transitively
                             code-grounded). Allowed: derived trust.
      * ``unverified-doc`` — an audited doc NOT yet verified (or self/circular). The
                             SUPPORTED resting on it is an echo → coerced to BLOCKED;
                             *may* clear once that dependency is verified.
      * ``excluded-doc``   — an excluded doc (CHANGELOG / ORIGINAL_SPEC / superpowers
                             / .planning — historical/frozen/scratch). Describes
                             past/intended state, never clears → coerced to
                             UNVERIFIABLE. Includes ANY unrecognized `.md` token: a
                             doc-shaped path we can't vouch for is treated as
                             un-groundable, never as code.
      * ``unresolved``     — no usable path token at all (empty / vague prose). No
                             evidence → coerced to UNVERIFIABLE. Closes the
                             "SUPPORTED with no grounding" hole.

    The grounding string is the agent-recorded source (a path, sometimes absolute,
    sometimes followed by a snippet). **Code-preferring:** if a real source path is
    present it wins, even alongside an incidental doc mention; only when there is no
    code evidence do we fall back to classifying the doc / unresolved tiers."""
    g = grounding.replace(str(_REPO_ROOT) + "/", "").strip()
    tokens = [t.strip("`,()[]<>\"'") for t in g.split()]
    pathish = [t for t in tokens if t and ("/" in t or "." in t)]
    # Code-preferring: a real non-doc source path is the strongest evidence.
    code = [
        t
        for t in pathish
        if not t.endswith(".md") and not _is_excluded(t) and t not in audited
    ]
    if code:
        return "code"
    for rel in pathish:
        if _is_excluded(rel):
            return "excluded-doc"
        if rel in audited:
            return "verified-doc" if rel in clean_verified else "unverified-doc"
    # A doc-shaped path we don't recognize is NEVER code — treat as ungroundable.
    if any(t.endswith(".md") for t in pathish):
        return "excluded-doc"
    return "unresolved"


def _record_verdicts(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist judged verdicts to the cache; re-stamp fully-clean docs.

    A doc is **clean** iff every submitted verdict for it is SUPPORTED **and**
    code-first-grounded — no CONTRADICTED, no UNVERIFIABLE, no BLOCKED. Code is the
    source of truth; the CLI re-derives each verdict's grounding tier and **coerces**
    a mis-labeled SUPPORTED so a sloppy judge can't launder drift:

      * SUPPORTED on an **unverified doc**  → **BLOCKED** (deferrable — re-queued
        once that dependency doc is verified), `blocked_on` = the dep doc(s).
      * SUPPORTED on an **excluded doc** (CHANGELOG) → **UNVERIFIABLE** (ungroundable
        — that source never clears; needs code or a human, never deferred).

    Only clean docs get re-stamped (last_validated + freshness manifest hash).
    Returns a per-doc summary for the drift report.
    """
    verdicts = payload.get("verdicts") or []
    cache = _load_cache()
    audited = _audited_doc_set()
    # Snapshot trust BEFORE this batch: a doc only counts as a clean grounding
    # source if it was already clean in a PRIOR run. This enforces topological
    # order — two mutually-referencing docs can't bootstrap each other's trust in
    # one batch; the cycle stays BLOCKED until a code-grounded base breaks it.
    clean_prev = _clean_verified_docs(cache)
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
        tier = _grounding_tier(grounding, audited, clean_prev)
        blocked_on = list(v.get("blocked_on") or [])
        # Coerce: code is the only source of truth, so a SUPPORTED that actually
        # rests on a non-clean doc — or on no resolvable evidence — is not proof.
        if verdict == "SUPPORTED" and tier == "unverified-doc":
            verdict = "BLOCKED"
        elif verdict == "SUPPORTED" and tier in ("excluded-doc", "unresolved"):
            verdict = "UNVERIFIABLE"
        if verdict == "BLOCKED" and not blocked_on:
            blocked_on = _blocked_on_from_grounding(grounding, audited, clean_prev)
        h = _claim_hash(claim, grounding)
        rec: dict[str, Any] = {
            "doc": doc,
            "claim": claim,
            "grounding": grounding,
            "verdict": verdict,
            "grounding_tier": tier,
            "evidence": v.get("evidence", ""),
        }
        if verdict == "BLOCKED":
            rec["blocked_on"] = blocked_on
        cache[h] = rec
        slot = per_doc.setdefault(
            doc,
            {"SUPPORTED": [], "CONTRADICTED": [], "UNVERIFIABLE": [], "BLOCKED": []},
        )
        item: dict[str, Any] = {"claim": claim, "evidence": v.get("evidence", "")}
        if verdict == "BLOCKED":
            item["blocked_on"] = blocked_on
        slot[verdict].append(item)

    _save_cache(cache)

    clean_docs = [
        doc
        for doc, s in per_doc.items()
        if not s["CONTRADICTED"] and not s["UNVERIFIABLE"] and not s["BLOCKED"]
    ]
    restamped = _restamp(clean_docs) if clean_docs else []
    # Refresh the deadlock report: if verification is now genuinely stuck (every
    # doc judged once, a mutually cross-dependent BLOCKED set remains), write it;
    # otherwise delete any stale one. Fail-soft — never break a --record.
    try:
        _refresh_blocked_report(cache)
    except Exception:
        pass
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
    """Human drift report: CONTRADICTED + UNVERIFIABLE + BLOCKED, per doc."""
    per_doc = summary["per_doc"]
    lines: list[str] = []
    drift = 0

    def _open(s: dict[str, list[Any]]) -> list[Any]:
        return s["CONTRADICTED"] + s["UNVERIFIABLE"] + s.get("BLOCKED", [])

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
        for item in s.get("BLOCKED", []):
            drift += 1
            deps = ", ".join(item.get("blocked_on") or []) or "an unverified doc"
            lines.append(
                f"  [BLOCKED] {item['claim']}"
                f"  (groundable only via {deps} — deferred until it is verified)"
            )
    n_docs = sum(1 for d in per_doc if _open(per_doc[d]))
    head = f"Doc verification: {drift} open item(s) across {n_docs} doc(s)."
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
    "--skip-fresh",
    "skip_fresh_days",
    type=int,
    default=DEFAULT_SKIP_FRESH_DAYS,
    show_default=True,
    help=(
        "Skip docs already prose-verified AND validated in the last N days AND "
        "unchanged since (verdict-cache hit + age < N + manifest-hash match) — "
        "applied in EVERY mode (--all/--changed/explicit) so a run never re-judges "
        "a doc already confirmed fresh. A doc whose last_validated came only from "
        "the human audit (never prose-judged) is never skipped. Kept below the "
        "weekly cadence (7d) so last week's sweep re-verifies; above one sweep's "
        "multi-day span so a sweep across sessions/days isn't redone. An edited doc "
        "(changed hash) is never skipped; code-affected docs (--changed via index) "
        "are never skipped. 0 disables."
    ),
)
@click.option(
    "--reset",
    "reset_audit",
    is_flag=True,
    help=(
        "Reset the verification baseline: stamp TODAY as the reset epoch so every "
        "doc validated before now counts as stale. Subsequent sweeps then re-verify "
        "the whole audited set incrementally (draining across sessions via the "
        "normal skip-fresh window) — for when you want to restart verification from "
        "scratch. Writes verify_reset_at to .claude/.doc-verify-sweep.json; mutates "
        "no docs and re-stamps nothing. This is an action: it resolves no packet."
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
    base: str,
    record_file: str | None,
    check_marker: bool,
    url: str | None,
    top_k: int,
    skip_fresh_days: int,
    reset_audit: bool,
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
    Skip-fresh (default 6 days) is applied in EVERY mode: docs already prose-verified
    (verdict-cache hit), validated < N days ago AND unchanged since are dropped. Docs
    never prose-judged (human-audit stamp only), edited docs (changed hash), and
    code-affected docs are never skipped; --skip-fresh 0 disables it for the run.

    \b
    Restart verification from scratch (durable, multi-session):
      brainpalace verify-docs --reset       # mark the whole set stale, then sweep
    --reset stamps today as the baseline epoch so docs validated earlier count as
    stale; later runs re-verify them incrementally. It mutates no docs.

    \b
    Record judged verdicts (the agent pipes them back):
      brainpalace verify-docs --record verdicts.json
      brainpalace verify-docs --record -            # stdin
    payload {verdicts:[{doc,claim,grounding,verdict,evidence,blocked_on?}]},
    verdict ∈ SUPPORTED|CONTRADICTED|UNVERIFIABLE|BLOCKED. The CLI re-derives each
    grounding's tier and coerces a mis-labeled SUPPORTED: on an unverified doc →
    BLOCKED (deferred until that dep is verified); on an excluded doc (CHANGELOG) →
    UNVERIFIABLE. Clean docs (all SUPPORTED) are re-stamped; the report lists
    CONTRADICTED + UNVERIFIABLE + BLOCKED. When every doc is judged but a cross-
    dependent BLOCKED cycle remains, a deadlock report is written to
    .claude/doc-verify-blocked.md for a human (deleted once the cycle clears).
    """
    _require_repo()
    if reset_audit:
        when = _stamp_reset()
        click.echo(
            f"verify-docs: verification baseline reset to {when}. Every doc "
            "validated before now is stale; subsequent sweeps will re-verify the "
            "whole audited set incrementally. No docs were modified."
        )
        return
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
    # Skip-fresh is ON by default in EVERY mode (--all, --changed, explicit paths);
    # disable per-run with --skip-fresh 0. The hash guard in _filter_fresh keeps it
    # safe (an edited doc has a changed hash → kept). A `--reset` baseline (epoch)
    # further forces re-verification of docs stamped before the reset. Only
    # `code-affected` entries are exempt: their prose is unchanged and their stamp
    # may be fresh, but the code they document moved, so skipping them would hide
    # exactly the drift the index lookup surfaced.
    effective_days = skip_fresh_days
    if effective_days > 0:
        reset_epoch = _load_reset_epoch()
        protected = [e for e in entries if e.get("trigger") == "code-affected"]
        filterable = [e for e in entries if e.get("trigger") != "code-affected"]
        kept, skipped = _filter_fresh(filterable, effective_days, reset_epoch)
        entries = protected + kept
        if skipped:
            # stderr — stdout carries the JSON packet the agent parses.
            click.echo(
                f"verify-docs: skipped {len(skipped)} fresh doc(s) "
                f"(validated < {effective_days}d, unchanged since): "
                f"{', '.join(skipped)}. Use --skip-fresh 0 to include them.",
                err=True,
            )
    # Defer blocked docs: a doc whose remaining claims ground only on a still-
    # unverified dependency is dropped from this packet until that dependency is
    # verified (it re-enters automatically then). This stops a cross-dependent doc
    # being re-judged every batch. Explicit paths / code-affected entries bypass it.
    cache = _load_cache()
    entries, deferred = _filter_blocked(entries, cache)
    if deferred:
        click.echo(
            f"verify-docs: deferred {len(deferred)} blocked doc(s) "
            f"(waiting on an unverified dependency): {', '.join(deferred)}.",
            err=True,
        )
    # Order smallest-prose-first: cheap docs (and, by correlation, dependency
    # leaves) lead, so a budget-capped batch clears more docs and builds the
    # verified base that unblocks dependents. Final sort — after every filter.
    entries = _order_by_cost(entries)
    # When nothing is left to judge, surface a deadlock report iff verification is
    # genuinely stuck (every doc judged, a cross-dependent BLOCKED cycle remains).
    if not entries:
        dead = _refresh_blocked_report(cache)
        if dead:
            click.echo(
                f"verify-docs: no docs left to judge — {len(dead)} doc(s) are "
                f"cross-dependent and cannot be verified. See {_BLOCKED_REPORT}.",
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
    click.echo(json.dumps(packet, indent=2))

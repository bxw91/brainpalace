#!/usr/bin/env bash
# PreToolUse guard — force *indexed-codebase* search through `brainpalace query`.
#
# Repo-dev tooling (project scope, NOT the shipped plugin). This repo is indexed
# by its own tool; CLAUDE.md / the AI guidance mandate `brainpalace query` for
# codebase search, not Grep/Glob/find. Instruction-level guidance is advisory and
# gets skipped — this hook enforces it at tool-call time.
#
# Behavior:
#   1. Fires on Grep, Glob, and Bash recursive content-search (grep -r/-R/
#      --include/--recursive, rg, ag). Plain `grep file` (non-recursive, piped
#      or not) and `find` are NOT intercepted — recursion is the gate, not
#      whether output is piped. A COMPOUND Bash command (`;`, `|`, `||`, `&&`,
#      `&`, or multi-line) is segmented and each segment analyzed on its own
#      (spec D1/D2), so a pipe target, a redirection, or a second command are
#      never misread as operands of the first — e.g. `grep -rn X . | head` IS
#      intercepted (recursive grep piped into a limiter), same as unpiped.
#   2. PATH-AWARE (matches the AI-guidance "Allowed Glob/Grep cases"): a search is
#      enforced ONLY when it targets content brainpalace actually INDEXES. The
#      indexed set is read from the persisted folder manifests
#      (.brainpalace/manifests/*.json -> `files`, absolute paths) — the ground
#      truth, so every real exclusion is honored with no hardcoded guesses. A
#      target is ALLOWED (grep passes through) when it is outside the project root
#      or absent from the manifest (e.g. node_modules, .git, build, excluded
#      subfolders). Routing a query for a folder brainpalace does not index is
#      pointless.
#   3. CLASSIFIED BY CONSTRUCT (spec D2/D3): a pattern containing a regex
#      construct BM25 cannot honor — character-class shorthand (\w \d \s \D \S
#      \W), a bracket expression ([...]), a quantifier (+ * ? {n,m}), or an
#      anchor (^ $) — is ALLOWED straight through to grep, no query run.
#      Plain literals AND alternation (foo\|bar) are faithful in BM25 (`|` is
#      not a `\w` char, so it acts as a delimiter and BM25 is already OR over
#      tokens) and still route to bm25. No config knob (D3): this is a
#      correctness fix, not a preference. A regex-construct pattern in ANY
#      segment of a compound command allows the WHOLE call (the hook
#      denies/allows per call, not per segment).
#   4. MULTIPLE SEARCH SEGMENTS (spec D4): if a compound command contains more
#      than one bm25-routable search segment (e.g. `grep -r A .; grep -r B .`),
#      the call is ALLOWED with a note rather than denied — a denial can only
#      carry the hits of one query, and denying the whole call while answering
#      just one half would leave the rest unanswered. Small bypass vector,
#      accepted for non-adversarial dev tooling; see D4 in the spec.
#   5. For an ENFORCED, single-segment, bm25-routable search: probe brainpalace;
#      if down, `brainpalace start` once + poll. Reachable -> run the
#      equivalent bm25 query in-hook. Hits -> DENY the tool and return them
#      inline (so callers lacking a Bash tool still get an answer). ZERO hits
#      (or no derivable term) -> ALLOW the original call: the index has
#      nothing for this exact token — it is either a not-yet-indexed recent
#      edit (watcher debounce) or genuinely absent, and grep is the
#      authoritative answer for both. Per-call only: the next search
#      re-probes and is denied again once the watcher catches up.
#      Still unreachable -> ALLOW (grep fallback) with a note.
#
# No manual skip override: the only fallbacks are non-indexed targets (step 2),
# a grep-only pattern or multi-segment compound (step 3/4), and a genuinely-
# unreachable server (step 5). Fail-soft: any error -> allow.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
hook_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- analyze: is this an indexed-codebase search? derive the query term -------
# Emits 5 lines: is_search(1/0), term, enforce(1/0), classify(bm25/grep/multi),
# scope (comma-joined --file-paths globs, absolute-anchored per D4 of the
# routing spec, may be empty). A Bash command is segmented on shell operators
# first (spec D1/D2 of the compound-command-parsing spec) and each segment
# analyzed independently; classify is "grep" if any segment is grep-class,
# "multi" if more than one bm25-routable segment survives (D4), else "bm25"
# for the single surviving segment. shlex tokenization means a hyphen inside a
# pattern (e.g. `grep -i foo-bar`) is never mistaken for a flag. Analyzer
# lives in search_guard_analyze.py (D6) so it is independently testable.
_an="$(printf '%s' "$input" | BP_ROOT="$project_dir" python3 "$hook_dir/search_guard_analyze.py" 2>/dev/null || true)"

is_search="$(printf '%s' "$_an" | sed -n 1p)"
term="$(printf '%s' "$_an" | sed -n 2p)"
enforce="$(printf '%s' "$_an" | sed -n 3p)"
classify="$(printf '%s' "$_an" | sed -n 4p)"
scope="$(printf '%s' "$_an" | sed -n 5p)"

[ "$is_search" = "1" ] || exit 0
if [ "$classify" = "grep" ]; then
  # D2/D3: a character class, quantifier, or anchor is a regex construct
  # BM25's \w+ tokenizer cannot honor faithfully — grep is authoritative,
  # not a fallback. No query is run.
  printf '{"systemMessage":"Pattern uses a regex construct (character class/quantifier/anchor) BM25 cannot match faithfully — allowing native grep for this call."}\n'
  exit 0
fi
if [ "$classify" = "multi" ]; then
  # D4: more than one bm25-routable search segment survived in this compound
  # command — a denial can only carry the hits of ONE query, so denying the
  # whole call would leave the rest unanswered. Allow, and say why.
  printf '{"systemMessage":"Compound command has more than one search segment — a single query cannot answer all of them, so this call is allowed as-is. Run each search individually through `brainpalace query --mode bm25` for indexed results."}\n'
  exit 0
fi
[ "$enforce"   = "1" ] || exit 0     # non-indexed / excluded target -> allow grep

# --- brainpalace liveness probe (+ auto-start & retry) -----------------------
runtime="$project_dir/.brainpalace/runtime.json"
base_url="http://127.0.0.1:8000"
read_url() {
  if [ -f "$runtime" ]; then
    local u; u="$(jq -r '.base_url // empty' "$runtime" 2>/dev/null || true)"
    [ -n "$u" ] && base_url="$u"
  fi
}
read_url
alive() { curl -s -o /dev/null --max-time 2 "$base_url/health" >/dev/null 2>&1; }

if ! alive; then
  if command -v brainpalace >/dev/null 2>&1; then
    ( cd "$project_dir" && timeout 40 brainpalace start >/dev/null 2>&1 ) || true
    read_url
    for _ in 1 2 3 4 5 6 7 8 9 10; do alive && break; sleep 1; done
  fi
fi

if ! alive; then
  printf '{"systemMessage":"brainpalace unreachable after a start attempt — allowing %s as a fallback for this call. Run `brainpalace start` / `brainpalace doctor` to restore enforced search."}\n' \
    "$(printf '%s' "$input" | jq -r '.tool_name // "search"')"
  exit 0
fi

# --- enforce: run the equivalent bm25 query in-hook, return hits inline ------
# D4/D5/D10: when a scope was derived (a path and/or --include was given),
# pass it through --file-paths so the search is answered FOR THAT SCOPE, not
# repo-wide (the defect this phase fixes). An absolute-anchored glob (D4) is
# required: a relative one returns 0 hits, which trips the zero-hit->ALLOW
# branch below and silently disables enforcement instead of scoping it.
bp_args=(query "$term" --mode bm25 --top-k 8 --json)
if [ -n "$scope" ]; then
  bp_args+=(--file-paths "$scope")
fi

results=""
if [ -n "$term" ] && command -v brainpalace >/dev/null 2>&1; then
  # A12/A19: carry (source, start_line, text) per hit -- NOT max-score-per-
  # source (two matches in one file are two grep lines, not one line-loss).
  # For a literal term, start_line + text[:text.find(term)].count("\n") lands
  # on the EXACT matching line (verified this session: 848 for the
  # useState<Window> case) because start_line is the line of the chunk's
  # first character, so counting newlines before the match offset adds
  # correctly even though the chunk starts mid-line. Two things degrade
  # gracefully instead of crashing or printing a false number: an alternation
  # term (post-Phase-1 the only non-literal pattern still reaching bm25) has
  # no verbatim substring to find, so text.find() misses -- fall back to the
  # chunk's first non-empty line, anchored at the chunk's own start_line
  # (approximate, never wrong-but-precise-looking). And ~29% of chunks (doc,
  # git_commit -- A19, measured) carry no start_line at all -- degrade to
  # "path: snippet" with no line number rather than printing None or 0.
  results="$( ( cd "$project_dir" && brainpalace "${bp_args[@]}" 2>/dev/null ) \
    | SG_TERM="$term" python3 -c '
import sys, json, os
term = os.environ.get("SG_TERM", "")
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
MAXLEN = 200
out = []
for r in d.get("results") or []:
    try:
        sc = float(r.get("score", 0))
    except Exception:
        sc = 0.0
    if sc <= 0.0:
        continue
    src = r.get("source") or "?"
    text = r.get("text") or ""
    start_line = r.get("start_line")
    idx = text.find(term) if term else -1
    snippet = ""
    line_no = None
    if idx >= 0:
        chunk_lines = text.split("\n")
        offset = text[:idx].count("\n")
        snippet = chunk_lines[offset] if offset < len(chunk_lines) else text[idx:idx + MAXLEN]
        if start_line is not None:
            line_no = start_line + offset
    else:
        # Alternation (or any non-literal-substring term): no match offset
        # to derive from, so use the first non-empty line of the chunk as
        # the snippet, anchored at the chunk start (not exact, never a crash
        # or a fabricated number).
        for cl in text.split("\n"):
            if cl.strip():
                snippet = cl
                break
        if start_line is not None:
            line_no = start_line
    snippet = snippet.strip()
    if len(snippet) > MAXLEN:
        snippet = snippet[:MAXLEN] + "..."
    if line_no is not None:
        out.append(f"  {src}:{line_no}: {snippet}")
    else:
        out.append(f"  {src}: {snippet}")
for ln in out[:8]:
    print(ln)
' 2>/dev/null || true)"
fi

if [ -z "$results" ]; then
  # Zero-hit bm25 (or empty/underivable term, or a mid-flight query error):
  # the index has nothing for this exact token — either a not-yet-indexed
  # recent edit (watcher debounce) or a genuinely absent term. Grep is the
  # authoritative answer for both, so denying here would be a false negative.
  # Allow the ORIGINAL call (preserves its exact semantics: -l/-n/context/
  # includes) rather than approximating grep in-hook. Per-call only.
  jq -n --arg t "$term" \
    '{systemMessage:("bm25 had no hits for \"" + $t + "\" — likely an unindexed recent edit or an absent token; allowing this search as ground truth. Once the watcher catches up, identical queries route through brainpalace again.")}'
  exit 0
fi

# A13/D9: print the ACTUAL invocation, scope included, not a hardcoded
# generic one -- a denial that hides its own command is unauditable (the
# caller cannot tell a bad query from a bad index) and unteachable (the
# same malformed search recurs). Mirrors bp_args above minus --json (the
# human-facing reproduction), so pasting this exact line reproduces the
# exact hits shown.
cmd="brainpalace query \"$term\" --mode bm25 --top-k 8"
if [ -n "$scope" ]; then
  cmd="$cmd --file-paths \"$scope\""
fi

body="Auto-ran \`$cmd\` — top hits:
$results"

reason="Codebase search over INDEXED content in this repo is served by brainpalace, not Grep/Glob/recursive-grep (CLAUDE.md — the repo is indexed by its own tool). This call is blocked and the equivalent keyword search was run for you below, so no caller is left without an answer. (Paths brainpalace does NOT index — outside the project root, or any folder/file absent from the folder manifest such as node_modules/.git/build — are NOT intercepted; grep them directly.) For concept search re-run \`brainpalace query \"...\" --mode hybrid\` / \`--mode vector\`; for relationships use \`--mode graph\`; add \`--json\` (keys: text/source/score/chunk_id) for scripting.

$body"

jq -n --arg r "$reason" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
exit 0

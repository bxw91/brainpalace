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
#      --include/--recursive, rg, ag). Plain `grep file` / piped grep and `find`
#      are NOT intercepted.
#   2. PATH-AWARE (matches the AI-guidance "Allowed Glob/Grep cases"): a search is
#      enforced ONLY when it targets content brainpalace actually INDEXES. The
#      indexed set is read from the persisted folder manifests
#      (.brainpalace/manifests/*.json -> `files`, absolute paths) — the ground
#      truth, so every real exclusion is honored with no hardcoded guesses. A
#      target is ALLOWED (grep passes through) when it is outside the project root
#      or absent from the manifest (e.g. node_modules, .git, build, excluded
#      subfolders). Routing a query for a folder brainpalace does not index is
#      pointless.
#   3. For an ENFORCED search: probe brainpalace; if down, `brainpalace start`
#      once + poll. Reachable -> run the equivalent bm25 query in-hook. Hits ->
#      DENY the tool and return them inline (so callers lacking a Bash tool
#      still get an answer). ZERO hits (or no derivable term) -> ALLOW the
#      original call: the index has nothing for this exact token — it is either
#      a not-yet-indexed recent edit (watcher debounce) or genuinely absent, and
#      grep is the authoritative answer for both. Per-call only: the next search
#      re-probes and is denied again once the watcher catches up.
#      Still unreachable -> ALLOW (grep fallback) with a note.
#
# No manual skip override: the only fallbacks are non-indexed targets (step 2) and
# a genuinely-unreachable server (step 3). Fail-soft: any error -> allow.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
command -v jq >/dev/null 2>&1 || exit 0
command -v curl >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"

# --- analyze: is this an indexed-codebase search? derive the query term -------
# Emits 3 lines: is_search(1/0), term, enforce(1/0). shlex tokenization means a
# hyphen inside a pattern (e.g. `grep -i foo-bar`) is never mistaken for a flag.
_an="$(printf '%s' "$input" | BP_ROOT="$project_dir" python3 -c '
import sys, os, json, shlex, glob

root = os.path.realpath(os.environ.get("BP_ROOT", "."))
try:
    data = json.load(sys.stdin)
except Exception:
    print("0"); print(""); print("0"); sys.exit(0)
tool = data.get("tool_name") or ""
ti = data.get("tool_input") or {}

# Ground truth = the persisted folder manifests (the exact set of
# indexed files, absolute paths). A path is "indexed" iff it is an indexed file
# or a directory that contains >=1 indexed file. This authoritatively honors
# every exclusion brainpalace actually applied (excluded subfolders are simply
# absent) with no hardcoded heuristics or config parsing that can drift.
def _load_index():
    files = set()
    for mp in glob.glob(os.path.join(root, ".brainpalace", "manifests", "*.json")):
        try:
            d = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        for k in (d.get("files") or {}):
            files.add(os.path.realpath(k))
    dirs = set()
    for f in files:                        # every ancestor dir of an indexed file
        d = os.path.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    return files, dirs

_FILES, _DIRS = _load_index()

def indexed(path):
    if not path:
        ap = root                          # no path -> search cwd == project root
    else:
        p = os.path.expanduser(path)
        ap = os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p))
    if _FILES or _DIRS:                     # manifest present -> authoritative
        return ap in _FILES or ap in _DIRS
    # fallback (manifest missing/unreadable): enforce inside root, allow outside
    return ap == root or ap.startswith(root + os.sep)

is_search = False; term = ""; paths = []
if tool in ("Grep", "Glob"):
    is_search = True
    term = ti.get("pattern") or ""
    if ti.get("path"):
        paths.append(ti["path"])
    elif tool == "Glob":
        pat = ti.get("pattern") or ""
        if pat[:1] in ("/", "~"):
            paths.append(pat.split("*")[0] or pat)
elif tool == "Bash":
    try:
        toks = shlex.split(ti.get("command") or "")
    except Exception:
        toks = (ti.get("command") or "").split()
    i = 0
    while i < len(toks):
        base = toks[i].split("/")[-1]
        if base in ("rg", "ag"):
            is_search = True
            j = i + 1; got = False
            while j < len(toks):
                t = toks[j]
                if t.startswith("-"): j += 1; continue
                if not got: term = t; got = True
                else: paths.append(t)
                j += 1
            break
        if base in ("grep", "egrep", "fgrep"):
            recursive = False; got = False; j = i + 1
            while j < len(toks):
                t = toks[j]
                if t == "--": j += 1; continue
                if t.startswith("--"):
                    if t in ("--recursive", "--include") or t.startswith("--include="):
                        recursive = True
                    j += 1; continue
                if t.startswith("-") and len(t) > 1:
                    if "r" in t or "R" in t: recursive = True
                    j += 1; continue
                if not got: term = t; got = True
                else: paths.append(t)
                j += 1
            if recursive: is_search = True
            break
        i += 1

if not is_search:
    print("0"); print(""); print("0"); sys.exit(0)
enforce = indexed("") if not paths else any(indexed(p) for p in paths)
print("1"); print(term); print("1" if enforce else "0")
' 2>/dev/null || true)"

is_search="$(printf '%s' "$_an" | sed -n 1p)"
term="$(printf '%s' "$_an" | sed -n 2p)"
enforce="$(printf '%s' "$_an" | sed -n 3p)"

[ "$is_search" = "1" ] || exit 0
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
results=""
if [ -n "$term" ] && command -v brainpalace >/dev/null 2>&1; then
  results="$( ( cd "$project_dir" && brainpalace query "$term" --mode bm25 --top-k 8 --json 2>/dev/null ) \
    | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
best = {}
for r in d.get("results") or []:
    try:
        sc = float(r.get("score", 0))
    except Exception:
        sc = 0.0
    if sc <= 0.0:
        continue
    src = r.get("source") or "?"
    if src not in best or sc > best[src]:
        best[src] = sc
for src, sc in sorted(best.items(), key=lambda x: -x[1])[:8]:
    print(f"  {src}  (score {round(sc, 2)})")
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

body="Auto-ran \`brainpalace query \"$term\" --mode bm25 --top-k 8\` — top hits:
$results"

reason="Codebase search over INDEXED content in this repo is served by brainpalace, not Grep/Glob/recursive-grep (CLAUDE.md — the repo is indexed by its own tool). This call is blocked and the equivalent keyword search was run for you below, so no caller is left without an answer. (Paths brainpalace does NOT index — outside the project root, or any folder/file absent from the folder manifest such as node_modules/.git/build — are NOT intercepted; grep them directly.) For concept search re-run \`brainpalace query \"...\" --mode hybrid\` / \`--mode vector\`; for relationships use \`--mode graph\`; add \`--json\` (keys: text/source/score/chunk_id) for scripting.

$body"

jq -n --arg r "$reason" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
exit 0
